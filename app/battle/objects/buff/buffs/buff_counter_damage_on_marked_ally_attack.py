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
class CounterDamageOnMarkedAllyAttackEvent(BuffEvent):
    """holder의 사거리 내 아군이 누군가를 공격할 때 발동한다. 그 공격자가
    reference_buff_id(예: 네브로스파스톤)를 보유하고 있다면, holder도 그
    공격의 대상에게 홀더의 공격 굴림 _PERCENT%만큼 추가 대미지를 입힌다.

    BuffContainer.on_ally_in_range_attacked()는 이 effect의 공격 대상
    (target_id)을 attacker_or_target으로 넘긴다. 실제 공격자가
    reference_buff_id를 보유했는지는 이 effect의 damage_data_list에서
    target_id가 일치하는 항목의 attacker_id들을 훑어 확인한다.

    홀더는 이 추가 대미지에서 실제로 공격을 가하는 쪽이므로, 홀더가 평소
    자신의 공격에 받는 "주는 대미지" 버프와 대상이 평소 자신이 공격당할 때
    받는 "받는 대미지" 버프가 정상 반영되어야 한다.
    apply_pure_damage_modifiers_to()로 이를 반영한다(reactive_damage.py 참고)."""

    _PERCENT: ClassVar[int] = 60
    reference_buff_id: str
    # 표시용 라벨. 여러 캐릭터가 이 클래스를 재사용할 수 있으므로 특정
    # 캐릭터의 스킬명을 하드코딩하지 않고, 이 버프를 등록한 스프레드시트
    # 행의 id를 그대로 쓴다.
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
        target_id = attacker_or_target
        if target_id == holder or target_id not in calculator.context.characters:
            return

        effect_data = calculator.data_by_effect[effect_seq_number]
        has_marked_attacker = any(
            dc.base.target_id == target_id
            and calculator.context.get_buff_stack(
                dc.base.attacker_id, self.reference_buff_id
            )
            > 0
            for dc in effect_data.damage_data_list
        )
        if not has_marked_attacker:
            return

        new_damage_calc = DamageCalculateData(
            base=DamageData(
                attacker_id=holder,
                target_id=target_id,
                value=BaseValueIndicator(
                    value_source=ValueSourceType.STAT_ATK_ROLL,
                    coefficient=FloatValueModifier(
                        source_name=f"{self.label}: {holder.name}", value=self._PERCENT
                    ),
                ),
            )
        )
        apply_pure_damage_modifiers_to(
            new_damage_calc, holder, target_id, calculator, effect_seq_number
        )


class BuffCounterDamageOnMarkedAllyAttack(BuffBase):
    """사거리 내에서 reference_buff_id로 지정된 아군이 누군가를 공격할
    때마다, 자신도 그 대상에게 추가 대미지를 입히는 버프."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ALLY_IN_RANGE_ATTACKED

    def create_event(self) -> CounterDamageOnMarkedAllyAttackEvent:
        assert self.reference_buff_id is not None
        return CounterDamageOnMarkedAllyAttackEvent(
            condition=self.condition,
            reference_buff_id=self.reference_buff_id,
            label=self.id,
        )
