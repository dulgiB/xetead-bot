import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
        self, targets: list[BattlefieldColumnIndex] | list[CharacterId]
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
        self, targets: list[BattlefieldColumnIndex] | list[CharacterId]
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
        self, targets: list[BattlefieldColumnIndex] | list[CharacterId]
    ) -> list[CharacterId]:
        target_id_list = []
        target_faction = self.context.characters[self.skill_holder_id].foe_faction

        assert all(isinstance(target, BattlefieldColumnIndex) for target in targets)
        for column in targets:
            target_id_list += self.context.position_map[target_faction][column].values()
        return target_id_list


@dataclass(frozen=True)
class SkillTargetRuleNamed(SkillTargetRule):
    """
    대상의 이름을 지정하여 사용 가능한 스킬 효과
    - 스킬 사용자의 공격 사거리 제한을 따름

    ex. 좌우 2칸 내의 아군을 1인 지정하여 회복, 전방 3칸 내의 적군을 1인 지정하여 공격_v
    """

    def get_targets(
        self, targets: list[BattlefieldColumnIndex] | list[CharacterId]
    ) -> list[CharacterId]:
        assert all(isinstance(target, CharacterId) for target in targets)
        return targets


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
        self, targets: list[BattlefieldColumnIndex] | list[CharacterId]
    ) -> list[CharacterId]:
        characters = [t for t in targets if isinstance(t, CharacterId)]
        columns = [t for t in targets if isinstance(t, BattlefieldColumnIndex)]

        if len(characters) != 1 or len(columns) > 1:
            raise CommandValidationError(error_invalid_command_format())

        if columns:
            target_pos = self.context.find_character_position(characters[0])
            if abs(target_pos.value - columns[0].value) != 1:
                raise CommandValidationError(
                    error_invalid_move_destination(columns[0])
                )

        return characters
