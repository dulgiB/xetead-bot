import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from utils.battle_helpers import is_reachable

from battle.objects.define import CombatStatType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class Condition(abc.ABC):
    value: Optional[int] = None

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
