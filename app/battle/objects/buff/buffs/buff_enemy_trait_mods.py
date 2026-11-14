"""에너미 특성용 모디파이어. "버프_패시브" 시트의 buff_mod_event 경로
(PassiveSkillData.buff_mod_event)로 상시 특성을 만들 수도 있고, "버프" 시트에
등록해 스킬로 몇 턴 동안 부여할 수도 있다."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class MaxAttackRollEvent(BuffEvent):
    """holder의 공격 굴림 주사위를 이 계산기 안에서 최대치로 고정한다.

    ON_ACTION은 피격 쪽에서도 불리지만, 굴림은 공격자 자신의 것만 읽으므로
    holder를 표시해 두기만 하면 된다."""

    supports_target_scope: ClassVar[bool] = True

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.PRE

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        scope = calculator.event_target_scope
        if scope is not None:
            calculator.max_roll_pairs.add((holder, scope))
            return
        calculator.max_roll_characters.add(holder)


class BuffMaxAttackRoll(BuffBase):
    """공격 굴림의 주사위가 항상 최대치(6)로 나온다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> MaxAttackRollEvent:
        return MaxAttackRollEvent(condition=self.condition)


@dataclass(frozen=True)
class IgnoreTauntEvent(BuffEvent):
    """계산 시점에는 아무것도 하지 않는다. 도발 무시는 대상을 정하는
    단계(taunt_redirect, _get_target_override)가 holder_ignores_taunt()로
    이 표시를 읽어 처리한다 — 계산 시점에는 대상이 이미 정해져 있다."""

    makes_holder_ignore_taunt: ClassVar[bool] = True

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        return


class BuffIgnoreTaunt(BuffBase):
    """보유자가 하는 모든 공격(기본 공격 포함)이 도발을 무시한다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> IgnoreTauntEvent:
        return IgnoreTauntEvent(condition=self.condition)

    def makes_holder_ignore_taunt(self) -> bool:
        return True


@dataclass(frozen=True)
class StripBuffsOnHitEvent(BuffEvent):
    """holder가 이번 effect에서 공격한 대상 각각의 버프를 그 대미지 뒤에
    전부 해제하도록 계산기에 요청한다(실제 해제는
    CommandPartCalculator._process_buff_strip()).

    ON_ACTION은 공격자/피격자 양쪽에서 호출되므로 attacker_id == holder인
    항목만 고른다."""

    supports_target_scope: ClassVar[bool] = True

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        effect_data = calculator.data_by_effect[effect_seq_number]
        requests = calculator._buff_strip_requests.setdefault(effect_seq_number, set())
        for damage_data in effect_data.damage_data_list:
            base = damage_data.base
            if base.attacker_id != holder or base.target_id == holder:
                continue
            if not calculator.in_event_scope(base.target_id):
                continue
            requests.add((holder, base.target_id))


class BuffStripBuffsOnHit(BuffBase):
    """보유자에게 공격당한 대상은 그 시점에 걸려 있던 버프(패시브 제외)가
    모두 해제된다. 디버프와 "기타"(해제 불가 마커·부적 등)는 건드리지 않는다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> StripBuffsOnHitEvent:
        return StripBuffsOnHitEvent(condition=self.condition)
