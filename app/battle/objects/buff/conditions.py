import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Iterator, Optional

from utils.battle_helpers import is_reachable

from battle.objects.define import BuffType, CombatStatType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_character import CombatCharacter


def _characters_in_holder_scope(
    context: "BattlefieldContext",
    holder: CharacterId,
    *,
    same_faction: bool,
    include_self: bool,
    in_range: bool,
) -> Iterator[tuple[CharacterId, "CombatCharacter"]]:
    """holder를 기준으로 (진영 일치 여부) × (자신 포함 여부) ×
    (같은 열 / 사거리 내) 조건에 맞는 캐릭터들을 순회한다. "같은 열"/"사거리
    내" 범위만 다른 조건들(AllyInSameColumnCondition, AllyInRangeCountCondition
    등)이 공유하는 순회 로직이다.

    동료(소환수, context.companion_owners)는 제외한다 — 슬롯을 차지하지 않고
    소환자의 위치를 그대로 따르는 종속 개체라 "진형에 아군이 몇 명 있는가"를
    세는 데 끼면 소환자 한 명이 두 명으로 잡힌다.
    SkillTargetRuleAllAllies/PassiveSkill._resolve_targets()의 아군 범위와
    같은 기준이다."""
    holder_char = context.characters.get(holder)
    if holder_char is None:
        return
    holder_pos = context.find_character_position(holder)
    holder_range = holder_char.status[CombatStatType.RANGE] if in_range else None

    for char_id, char in context.characters.items():
        if not include_self and char_id == holder:
            continue
        if char_id in context.companion_owners:
            continue
        if (char.faction == holder_char.faction) != same_faction:
            continue
        if in_range:
            assert holder_range is not None  # in_range=True일 때만 여기 도달
            if not is_reachable(
                holder_pos, context.find_character_position(char_id), holder_range
            ):
                continue
        elif context.find_character_position(char_id) != holder_pos:
            continue
        yield char_id, char


def _any_damaged_in_holder_scope(
    context: "BattlefieldContext",
    holder: CharacterId,
    damaged: set[CharacterId],
    *,
    include_self: bool,
) -> bool:
    """holder의 사거리 이내·같은 진영 캐릭터 중 `damaged`에 든 자가 있는지.
    "이번 라운드"(damaged_this_round)와 "지난 라운드"
    (prev_damaged_this_round) 조건이 읽는 집합만 다르고 나머지가 같아
    한곳에 모은다."""
    return any(
        char_id in damaged
        for char_id, _ in _characters_in_holder_scope(
            context, holder, same_faction=True, include_self=include_self, in_range=True
        )
    )


@dataclass(frozen=True)
class Condition(abc.ABC):
    value: Optional[int] = None

    # True면 PassiveSkillWrapperBuff.timing이 적의 지연 공격이 모두 적용된 뒤로
    # 평가를 미룬다. 직접 오버라이드하지 말고 RoundResolvedCondition을 상속한다.
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
class RoundResolvedCondition(Condition):
    """damaged_this_round 등 이번 라운드에 확정된 데이터를 읽는 조건의 공통
    부모. 이 조건을 쓰는 새 클래스는 requires_round_resolved를 따로 켤 필요
    없이 이 클래스를 상속하기만 하면 된다."""

    requires_round_resolved: ClassVar[bool] = True


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
            not buff.duration.is_passive and buff.buff_type == BuffType.BUFF
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
            not buff.duration.is_passive and buff.buff_type == BuffType.DEBUFF
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
        return any(
            _characters_in_holder_scope(
                context, holder, same_faction=True, include_self=False, in_range=False
            )
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
        enemy_count = sum(
            1
            for _ in _characters_in_holder_scope(
                context, holder, same_faction=False, include_self=True, in_range=True
            )
        )
        assert self.value is not None
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
        ally_count = sum(
            1
            for _ in _characters_in_holder_scope(
                context, holder, same_faction=True, include_self=False, in_range=True
            )
        )
        assert self.value is not None
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
class HolderWasAttackedCondition(RoundResolvedCondition):
    """holder가 이번 라운드 동안(damaged_this_round 기준) 대미지를 받았을 때 True.

    "같은 열 아군 누구든" 대신 "자신이 맞았을 때만" 추가로 반응하는 조건에 쓴다.
    """

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return holder in context.damaged_this_round


@dataclass(frozen=True)
class AllyInSameColumnWasAttackedCondition(RoundResolvedCondition):
    """holder와 같은 열·같은 진영(자신 포함)인 캐릭터 중 이번 라운드 동안
    (damaged_this_round 기준) 대미지를 받은 자가 1명이라도 있으면 True."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return any(
            char_id in context.damaged_this_round
            for char_id, _ in _characters_in_holder_scope(
                context, holder, same_faction=True, include_self=True, in_range=False
            )
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
class AllyInRangeWasAttackedCondition(RoundResolvedCondition):
    """holder의 사거리 이내(자신 포함)·같은 진영인 캐릭터 중 이번 라운드
    동안(damaged_this_round 기준) 대미지를 받은 자가 1명이라도 있으면 True.
    "라운드 최종 위치 기준"은 별도 처리가 필요 없다 — 라운드 종료 시점에
    find_character_position()을 호출하면 자연히 그 라운드의 최종 위치가
    나온다."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return _any_damaged_in_holder_scope(
            context, holder, context.damaged_this_round, include_self=True
        )


@dataclass(frozen=True)
class OtherAllyInRangeWasAttackedCondition(RoundResolvedCondition):
    """holder의 사거리 이내·같은 진영이면서 holder 자신은 제외한 캐릭터 중
    이번 라운드 동안(damaged_this_round 기준) 대미지를 받은 자가 1명이라도
    있으면 True. holder 자신이 맞은 것만으로는 발동하지 않는다는 점에서
    AllyInRangeWasAttackedCondition(자신 포함)과 구분된다."""

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return _any_damaged_in_holder_scope(
            context, holder, context.damaged_this_round, include_self=False
        )


@dataclass(frozen=True)
class OtherAllyInRangeWasAttackedLastRoundCondition(Condition):
    """OtherAllyInRangeWasAttackedCondition과 같은 판정을 **지난 라운드**의
    피격 기록(prev_damaged_this_round)으로 한다.

    "지난 라운드에 아군이 맞았으면 이번 라운드 동안 버프" 같은 효과는 라운드
    종료 트리거로 걸면 안 된다 — 같은 on_round_end()가 곧바로 턴을 차감해
    지속시간이 1턴 짧아지고, 그 차감을 유예하는 대련/상시전투와 본 전투의
    결과가 갈린다. 라운드 시작 트리거 + 이 조건으로 표현하면 지속시간을
    설명 그대로(1턴) 적을 수 있고 모드와 무관하게 같게 동작한다.

    라운드 시작 시점엔 아직 아무도 움직이지 않았으므로 사거리 판정도 지난
    라운드의 최종 위치 기준이 된다.
    """

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        return _any_damaged_in_holder_scope(
            context, holder, context.prev_damaged_this_round, include_self=False
        )
