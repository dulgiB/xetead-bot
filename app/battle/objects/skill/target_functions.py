import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from battle.exceptions import (
    CommandValidationError,
    error_invalid_command_format,
    error_invalid_move_destination,
)
from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class SkillTargetRule(abc.ABC):
    context: "BattlefieldContext"
    skill_holder_id: CharacterId

    @property
    def ignores_input_targets(self) -> bool:
        return False

    @abc.abstractmethod
    def get_targets(
        self, targets: list[BattlefieldColumnIndex | CharacterId]
    ) -> list[CharacterId]:
        pass


@dataclass(frozen=True)
class SkillTargetRuleSelf(SkillTargetRule):
    """
    자신을 대상으로 하는 스킬 효과

    ex. 자신에게 버프 부여, 자신의 체력을 회복, 자신의 체력을 10 소모
    """

    @property
    def ignores_input_targets(self) -> bool:
        return True

    def get_targets(
        self, targets: list[BattlefieldColumnIndex | CharacterId]
    ) -> list[CharacterId]:
        return [self.skill_holder_id]


@dataclass(frozen=True)
class SkillTargetRuleColumn(SkillTargetRule):
    """
    사용자의 사거리 내 0-6 사이의 위치 index를 기준으로 하는 스킬 효과
    - 인원 상한 없음 (광역기 개념)

    ex. 본인의 현재 위치가 3열이고 사거리가 1이면
    "2슬롯을 공격한다"는 효과로 2, 3열을 대상으로 지정해서 사용 가능
    """

    def get_targets(
        self, targets: list[BattlefieldColumnIndex | CharacterId]
    ) -> list[CharacterId]:
        target_id_list: list[CharacterId] = []
        target_faction = self.context.characters[self.skill_holder_id].foe_faction

        assert all(isinstance(target, BattlefieldColumnIndex) for target in targets)
        columns = cast(list[BattlefieldColumnIndex], targets)
        for column in columns:
            target_id_list += self.context.position_map[target_faction][column].values()

        # position_map 슬롯을 차지하지 않는 동료(예: 소환수)는 열 대상에
        # 독립적으로 포함시키지 않는다 — owner만 맞은 것으로 취급하고, 가디언
        # 버프가 있다면 그 1회분 대미지를 owner/동료가 나눠 받는다(단일 대상
        # 공격과 동일한 분담 경로). 동료를 여기서 함께 넣으면 owner와 동료가
        # 각자 전체 대미지를 따로 맞는 셈이 되어 실질 피해량이 2배가 된다.
        return target_id_list


@dataclass(frozen=True)
class SkillTargetRuleColumnRange(SkillTargetRule):
    """
    사용자의 사거리 내 열 1개를 지정하면, 그 열을 중심으로 좌우 2열씩
    확장한 최대 5개 열(총 5열) 전체를 대상으로 하는 스킬 효과.
    필드 경계를 넘어가는 열은 자연히 제외되어 5개 미만이 될 수 있다.
    - 대상 진영은 SkillTargetRuleColumn과 동일하게 항상 시전자의 적 진영.
    - 인원 상한 없음 (광역기 개념)

    ex. 본인의 사거리 내 열 하나를 지정해 그 열 ±2열, 총 5열의 적 전체를 공격
    """

    COLUMN_RANGE_RADIUS = 2

    def get_targets(
        self, targets: list[BattlefieldColumnIndex | CharacterId]
    ) -> list[CharacterId]:
        target_id_list: list[CharacterId] = []
        target_faction = self.context.characters[self.skill_holder_id].foe_faction

        assert all(isinstance(target, BattlefieldColumnIndex) for target in targets)
        columns = cast(list[BattlefieldColumnIndex], targets)

        expanded_column_values: set[int] = set()
        for column in columns:
            for offset in range(
                -self.COLUMN_RANGE_RADIUS, self.COLUMN_RANGE_RADIUS + 1
            ):
                candidate = column.value + offset
                if 0 <= candidate < BattlefieldColumnIndex.NONE.value:
                    expanded_column_values.add(candidate)

        for column_value in sorted(expanded_column_values):
            column = BattlefieldColumnIndex(column_value)
            target_id_list += self.context.position_map[target_faction][column].values()

        return target_id_list


@dataclass(frozen=True)
class SkillTargetRuleAllyColumn(SkillTargetRule):
    """
    사용자의 사거리 내 0-6 사이의 위치 index를 기준으로, 시전자와 같은 진영의
    캐릭터를 대상으로 하는 스킬 효과 (아군 대상 열 광역)
    - 인원 상한 없음 (광역기 개념)

    ex. 자신의 사거리 내 아군 열 하나를 지정해 그 열의 아군 전체에게 버프 부여
    """

    def get_targets(
        self, targets: list[BattlefieldColumnIndex | CharacterId]
    ) -> list[CharacterId]:
        target_id_list: list[CharacterId] = []
        target_faction = self.context.characters[self.skill_holder_id].faction

        assert all(isinstance(target, BattlefieldColumnIndex) for target in targets)
        columns = cast(list[BattlefieldColumnIndex], targets)
        for column in columns:
            target_id_list += self.context.position_map[target_faction][column].values()
        return target_id_list


@dataclass(frozen=True)
class SkillTargetRuleAllAllies(SkillTargetRule):
    """
    시전자와 동일 진영의 모든 캐릭터를 대상으로 하는 스킬 효과. 시전자
    자신과 동료(소환수 등, position_map 슬롯을 차지하지 않는 존재)는
    대상에서 제외한다.
    - 열/이름 입력을 받지 않는다(ignores_input_targets=True).
    - 인원 상한 없음 (광역기 개념)

    ex. 자신을 희생해 자신을 제외한 아군 전체를 회복
    """

    @property
    def ignores_input_targets(self) -> bool:
        return True

    def get_targets(
        self, targets: list[BattlefieldColumnIndex | CharacterId]
    ) -> list[CharacterId]:
        holder = self.context.characters[self.skill_holder_id]
        return [
            char_id
            for char_id, char in self.context.characters.items()
            if char_id != self.skill_holder_id
            and char_id not in self.context.companion_owners
            and char.faction == holder.faction
        ]


@dataclass(frozen=True)
class SkillTargetRuleNamed(SkillTargetRule):
    """
    대상의 이름을 지정하여 사용 가능한 스킬 효과
    - 스킬 사용자의 공격 사거리 제한을 따름

    ex. 좌우 2칸 내의 아군을 1인 지정하여 회복, 전방 3칸 내의 적군을 1인 지정하여 공격_v
    """

    def get_targets(
        self, targets: list[BattlefieldColumnIndex | CharacterId]
    ) -> list[CharacterId]:
        assert all(isinstance(target, CharacterId) for target in targets)
        return cast(list[CharacterId], targets)


@dataclass(frozen=True)
class SkillTargetRuleNamedWithColumn(SkillTargetRule):
    """
    캐릭터 1명과 그 캐릭터에 인접한 열 1개(생략 가능)를 동시에 지정하는 스킬 효과.
    - 열을 지정하지 않으면 이동 없이 캐릭터만 대상이 된다.
    - 열을 지정하면 대상 캐릭터의 "현재 위치" 기준 ±1열이어야 한다.

    ex. 스킬/스킬명/대상A       (열 생략)
        스킬/스킬명/대상A/3열   (대상A를 3열로 이동)
    """

    def get_targets(
        self, targets: list[BattlefieldColumnIndex | CharacterId]
    ) -> list[CharacterId]:
        characters = [t for t in targets if isinstance(t, CharacterId)]
        columns = [t for t in targets if isinstance(t, BattlefieldColumnIndex)]

        if len(characters) != 1 or len(columns) > 1:
            raise CommandValidationError(error_invalid_command_format())

        if columns:
            target_pos = self.context.find_character_position(characters[0])
            if abs(target_pos.value - columns[0].value) != 1:
                raise CommandValidationError(error_invalid_move_destination(columns[0]))

        return characters
