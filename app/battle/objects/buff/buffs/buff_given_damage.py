from dataclasses import dataclass

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import CommandCalculator
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueType
from battle.objects.models import CharacterId, FloatValueModifier, IntValueModifier


@dataclass(frozen=True)
class GivenDamageModEvent(BuffEvent):
    value: IntValueModifier | FloatValueModifier

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: BattlefieldContext,
        calculator: CommandCalculator,
    ) -> None:
        for damage_data in calculator.damage_data_list:
            if damage_data.base.attacker_id == holder:
                damage_data.modifiers.append(self.value)


@dataclass
class BuffGivenDamage(BuffBase):
    """주는 대미지 증가/감소"""

    @property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ATTACK}

    def create_event(self) -> GivenDamageModEvent:
        if self.value_type == ValueType.INTEGER:
            return GivenDamageModEvent(
                condition=self.condition, value=IntValueModifier(self.value)
            )
        elif self.value_type == ValueType.PERCENT:
            return GivenDamageModEvent(
                condition=self.condition, value=FloatValueModifier(self.value)
            )
        else:
            raise ValueError(self.value_type)
