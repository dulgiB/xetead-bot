from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueType
from battle.objects.models import (
    CharacterId,
    FloatValueModifier,
    IntValueModifier,
    ValueModifierBase,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class GivenDamageModEvent(BuffEvent):
    value: ValueModifierBase

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
        for damage_data in calculator.data_by_effect[
            effect_seq_number
        ].damage_data_list:
            if damage_data.base.attacker_id == holder:
                damage_data.modifiers.append(self.value)


class BuffGivenDamage(BuffBase):
    """주는 대미지 증가/감소"""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> GivenDamageModEvent:
        if self.value_type == ValueType.INTEGER:
            return GivenDamageModEvent(
                condition=self.condition,
                value=IntValueModifier(source_name=self.id, value=self.value),
            )
        elif self.value_type == ValueType.PERCENT:
            return GivenDamageModEvent(
                condition=self.condition,
                value=FloatValueModifier(source_name=self.id, value=self.value),
            )
        else:
            raise ValueError(self.value_type)
