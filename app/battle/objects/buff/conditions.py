import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Optional

from utils.battle_helpers import is_reachable

from battle.objects.define import CombatStatType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class Condition(abc.ABC):
    value: Optional[int] = None

    # 이번 라운드에 이미 확정된 결과(damaged_this_round 등)에 의존하는 조건이면
    # True로 오버라이드한다. ENEMY_POST_ACTION 트리거 패시브가 적의 지연 공격이
    # 모두 적용된 뒤에 평가되어야 하는지 PassiveSkillWrapperBuff.timing이
    # 판단하는 데 쓰인다(app/battle/objects/passive_skill/passive_skill.py 참고).
    requires_round_resolved: ClassVar[bool] = False

    @abc.abstractmethod
    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        pass


@dataclass(frozen=True)
class IsInSameColumnCondition(Condition):
    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if attacker_or_target is None:
            return False

        return context.find_character_position(
            holder
        ) == context.find_character_position(attacker_or_target)


@dataclass(frozen=True)
class WasNotAttackedCondition(Condition):
    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        for part_result in context.prev_round_results:
            for data in part_result.expanded_part.data_per_effect:
                if data is None:
                    continue
                if holder in [d.target_id for d in data.damage_list]:
                    return False
        return True


@dataclass(frozen=True)
class SelfHpBelowCondition(Condition):
    """holder의 현재 체력 비율이 value% 미만일 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        char = context.characters.get(holder)
        if char is None:
            return False
        max_hp = char.status[CombatStatType.MAX_HP]
        if max_hp == 0:
            return False
        return (char.status.curr_hp / max_hp * 100) < self.value


@dataclass(frozen=True)
class HolderHasBuffCondition(Condition):
    """holder에게 패시브가 아닌 버프가 1개 이상 있을 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return any(
            not buff.duration.is_passive and not buff.is_debuff
            for buff in context.buff_container.get_buffs_by(holder, None)
        )


@dataclass(frozen=True)
class TargetHasDebuffCondition(Condition):
    """attacker_or_target에게 패시브가 아닌 디버프가 1개 이상 있을 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if attacker_or_target is None:
            return False
        return any(
            not buff.duration.is_passive and buff.is_debuff
            for buff in context.buff_container.get_buffs_by(attacker_or_target, None)
        )


@dataclass(frozen=True)
class AllyInSameColumnCondition(Condition):
    """holder와 같은 열에 같은 진영 캐릭터가 1명 이상 있을 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if holder not in context.characters:
            return False
        holder_char = context.characters[holder]
        holder_pos = context.find_character_position(holder)
        return any(
            char_id != holder
            and char.faction == holder_char.faction
            and context.find_character_position(char_id) == holder_pos
            for char_id, char in context.characters.items()
        )


@dataclass(frozen=True)
class TargetAttackedHolderLastRoundCondition(Condition):
    """직전 라운드에 attacker_or_target이 holder를 공격했을 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if attacker_or_target is None:
            return False
        for part_result in context.prev_round_results:
            for data in part_result.expanded_part.data_per_effect:
                if data is None:
                    continue
                for damage in data.damage_list:
                    if (
                        damage.attacker_id == attacker_or_target
                        and damage.target_id == holder
                    ):
                        return True
        return False


@dataclass(frozen=True)
class HolderDidNotMoveThisTurnCondition(Condition):
    """이번 라운드에 holder가 이동 커맨드를 사용하지 않았을 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return holder not in context.moved_this_round


@dataclass(frozen=True)
class SameTargetAsLastRoundCondition(Condition):
    """직전 라운드에도 holder가 attacker_or_target을 공격했을 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if attacker_or_target is None:
            return False
        for part_result in context.prev_round_results:
            for data in part_result.expanded_part.data_per_effect:
                if data is None:
                    continue
                for damage in data.damage_list:
                    if (
                        damage.attacker_id == holder
                        and damage.target_id == attacker_or_target
                    ):
                        return True
        return False


@dataclass(frozen=True)
class HealedNonSelfCondition(Condition):
    """holder가 자신 외 대상에게 회복을 부여하는 상황(attacker_or_target != holder)일 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return attacker_or_target is not None and attacker_or_target != holder


@dataclass(frozen=True)
class EnemyInRangeCountCondition(Condition):
    """holder의 사거리 내 적 수가 value명 이상일 때 True. PassiveSkill 조건 등에 사용."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        holder_char = context.characters.get(holder)
        if holder_char is None:
            return False
        holder_pos = context.find_character_position(holder)
        holder_range = holder_char.status[CombatStatType.RANGE]
        enemy_count = sum(
            1
            for char_id, char in context.characters.items()
            if char.faction != holder_char.faction
            and is_reachable(
                holder_pos, context.find_character_position(char_id), holder_range
            )
        )
        return enemy_count >= self.value


@dataclass(frozen=True)
class AllyInRangeCountCondition(Condition):
    """holder의 사거리 내 아군(자신 제외) 수가 value명 이상일 때 True. 패시브 스킬 조건 등에 사용."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        holder_char = context.characters.get(holder)
        if holder_char is None:
            return False
        holder_pos = context.find_character_position(holder)
        holder_range = holder_char.status[CombatStatType.RANGE]
        ally_count = sum(
            1
            for char_id, char in context.characters.items()
            if char_id != holder
            and char.faction == holder_char.faction
            and is_reachable(
                holder_pos, context.find_character_position(char_id), holder_range
            )
        )
        return ally_count >= self.value


@dataclass(frozen=True)
class TargetIsInRangeCondition(Condition):
    """attacker_or_target이 holder의 사거리 내에 있을 때 True. ON_ENEMY_MOVE 견제 패시브 등에 사용."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if attacker_or_target is None:
            return False
        holder_char = context.characters.get(holder)
        if holder_char is None:
            return False
        holder_pos = context.find_character_position(holder)
        target_pos = context.find_character_position(attacker_or_target)
        holder_range = holder_char.status[CombatStatType.RANGE]
        return is_reachable(holder_pos, target_pos, holder_range)


@dataclass(frozen=True)
class HolderWasAttackedCondition(Condition):
    """holder가 이번 라운드 동안(damaged_this_round 기준) 대미지를 받았을 때 True.

    "같은 열 아군 누구든" 대신 "자신이 맞았을 때만" 추가로 반응하는 조건에 쓴다.
    """

    requires_round_resolved: ClassVar[bool] = True

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return holder in context.damaged_this_round


@dataclass(frozen=True)
class AllyInSameColumnWasAttackedCondition(Condition):
    """holder와 같은 열·같은 진영(자신 포함)인 캐릭터 중 이번 라운드 동안
    (damaged_this_round 기준) 대미지를 받은 자가 1명이라도 있으면 True."""

    requires_round_resolved: ClassVar[bool] = True

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if holder not in context.characters:
            return False
        holder_char = context.characters[holder]
        holder_pos = context.find_character_position(holder)
        return any(
            char.faction == holder_char.faction
            and context.find_character_position(char_id) == holder_pos
            and char_id in context.damaged_this_round
            for char_id, char in context.characters.items()
        )


@dataclass(frozen=True)
class TargetIsAllyCondition(Condition):
    """attacker_or_target이 holder와 같은 진영(아군)일 때 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if attacker_or_target is None:
            return False
        holder_char = context.characters.get(holder)
        target_char = context.characters.get(attacker_or_target)
        if holder_char is None or target_char is None:
            return False
        return holder_char.faction == target_char.faction


@dataclass(frozen=True)
class AllyInRangeWasAttackedCondition(Condition):
    """holder의 사거리 이내(자신 포함)·같은 진영인 캐릭터 중 이번 라운드
    동안(damaged_this_round 기준) 대미지를 받은 자가 1명이라도 있으면 True.
    "라운드 최종 위치 기준"은 별도 처리가 필요 없다 — 라운드 종료 시점에
    find_character_position()을 호출하면 자연히 그 라운드의 최종 위치가
    나온다."""

    requires_round_resolved: ClassVar[bool] = True

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        holder_char = context.characters.get(holder)
        if holder_char is None:
            return False
        holder_pos = context.find_character_position(holder)
        holder_range = holder_char.status[CombatStatType.RANGE]
        return any(
            char.faction == holder_char.faction
            and is_reachable(
                holder_pos, context.find_character_position(char_id), holder_range
            )
            and char_id in context.damaged_this_round
            for char_id, char in context.characters.items()
        )
