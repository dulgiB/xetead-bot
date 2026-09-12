from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Optional

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueType
from battle.objects.models import CharacterId, FloatValueModifier

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class GivenDamageAgainstDebuffModEvent(BuffEvent):
    """condition(보통 TargetHasDebuffCondition)이 충족될 때 value만큼 주는 대미지를
    올리고, 공격 대상이 bonus_buff_id까지 보유하고 있으면 bonus_value를 추가로
    더한다. bonus_buff_id가 None이면 추가분은 영영 붙지 않는다."""

    is_pure_damage_modifier: ClassVar[bool] = True

    value: FloatValueModifier
    bonus_value: FloatValueModifier
    bonus_buff_id: Optional[str]

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
        target_has_bonus_buff = (
            self.bonus_buff_id is not None
            and attacker_or_target is not None
            and any(
                buff.id == self.bonus_buff_id
                for buff in calculator.context.buff_container.get_buffs_by(
                    attacker_or_target, None
                )
            )
        )
        for damage_data in calculator.data_by_effect[
            effect_seq_number
        ].damage_data_list:
            if damage_data.base.attacker_id == holder:
                damage_data.given_modifiers.append(self.value)
                if target_has_bonus_buff:
                    damage_data.given_modifiers.append(self.bonus_value)


class BuffGivenDamageAgainstDebuff(BuffBase):
    """디버프가 걸린 적을 공격하면 주는 대미지가 value% 증가한다. 대상에게
    reference_buff_id 디버프까지 있으면 추가로 value_2%만큼 더 증가한다(항상
    퍼센트로 해석).
    추가분의 조건이 되는 버프 id는 시트의 reference_buff_id에서 온다.

    반드시 condition=TargetHasDebuffCondition과 함께 등록해야 한다 — 대상에게
    디버프가 전혀 없으면 이 버프 자체가 애초에 발동하지 않아야 하기 때문이다.
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> GivenDamageAgainstDebuffModEvent:
        if self.value_type != ValueType.PERCENT:
            raise ValueError(self.value_type)
        return GivenDamageAgainstDebuffModEvent(
            condition=self.condition,
            value=FloatValueModifier(source_name=self.id, value=self.value),
            bonus_value=FloatValueModifier(source_name=self.id, value=self.value_2),
            bonus_buff_id=self.reference_buff_id,
        )
