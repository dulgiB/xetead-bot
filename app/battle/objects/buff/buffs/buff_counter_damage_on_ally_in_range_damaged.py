from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from battle.core.commands.models import DamageCalculateData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.buff.reactive_damage import apply_pure_damage_modifiers_to
from battle.objects.define import BuffApplyTiming, ValueSourceType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    DamageData,
    FloatValueModifier,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class CounterDamageOnAllyInRangeDamagedEvent(BuffEvent):
    """holder의 사거리 내 아군이 대미지를 받을 때(홀더 자신 포함) 발동한다.
    공격자에게 홀더의 공격 굴림 _ALLY_PERCENT%만큼 반격 대미지를 입히되,
    맞은 아군이 홀더 자신이면 _SELF_PERCENT%를 대신 적용한다.

    "맞은 아군이 홀더 자신인지"는 이 effect의 damage_data_list를 훑어
    target_id == holder인 항목이 있는지로 판정한다(CompanionGuardianEvent와
    동일한 방식). 한 effect(광역기 등)가 같은 공격자로 홀더와 다른 아군을
    동시에 맞히는 극히 드문 경우, 그 다른 아군에 대한 반격도 _SELF_PERCENT%로
    계산되는 근사가 있을 수 있다 — BuffContainer.on_ally_in_range_damaged()가
    호출당 정확한 피격자 id를 넘기지만, apply()는 홀더/공격자 id 2개만 받는
    표준 인터페이스를 그대로 쓰기 위한 트레이드오프다.

    홀더는 이 반격에서 실제로 공격을 가하는 쪽이므로, 반격 대미지에도 홀더가
    평소 자신의 공격에 받는 "주는 대미지" 버프(예: [오데])와 공격자가 평소
    자신이 공격당할 때 받는 "받는 대미지" 버프가 정상 반영되어야 한다.
    apply_pure_damage_modifiers_to()로 이를 반영한다(reactive_damage.py 참고)."""

    _SELF_PERCENT: ClassVar[int] = 80
    _ALLY_PERCENT: ClassVar[int] = 50

    # 표시용 라벨. 여러 캐릭터가 이 클래스를 재사용할 수 있으므로 특정
    # 캐릭터의 스킬명을 하드코딩하지 않고, 이 버프를 등록한 스프레드시트
    # 행의 id를 그대로 쓴다(BuffGivenDamage 등과 동일한 관례).
    label: str

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
        attacker_id = attacker_or_target
        if attacker_id == holder or attacker_id not in calculator.context.characters:
            return

        effect_data = calculator.data_by_effect[effect_seq_number]
        is_self_hit = any(
            dc.base.target_id == holder for dc in effect_data.damage_data_list
        )
        percent = self._SELF_PERCENT if is_self_hit else self._ALLY_PERCENT

        new_damage_calc = DamageCalculateData(
            base=DamageData(
                attacker_id=holder,
                target_id=attacker_id,
                value=BaseValueIndicator(
                    value_source=ValueSourceType.STAT_ATK_ROLL,
                    coefficient=FloatValueModifier(
                        source_name=f"{self.label}: {holder.name}", value=percent
                    ),
                ),
            )
        )
        apply_pure_damage_modifiers_to(
            new_damage_calc, holder, attacker_id, calculator, effect_seq_number
        )


class BuffCounterDamageOnAllyInRangeDamaged(BuffBase):
    """자신에게 (패시브가 아닌) 버프가 부여되어 있을 때, 사거리 내 아군이
    공격받으면 공격자에게 반격 대미지를 입히는 패시브. 자신이 맞은 경우
    반격 비율이 더 높다. 전투 시작 시 1회 부여되는 영구(패시브) 버프."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ALLY_IN_RANGE_DAMAGED

    def create_event(self) -> CounterDamageOnAllyInRangeDamagedEvent:
        return CounterDamageOnAllyInRangeDamagedEvent(
            condition=self.condition, label=self.id
        )
