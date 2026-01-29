from dataclasses import dataclass

from battle.objects.buff.buff_base import BuffBase, BuffValueType
from battle.objects.buff.buff_events import BuffEvent
from battle.objects.define import BuffApplyTiming
from battle.objects.models import FloatValueModifier, IntValueModifier


@dataclass(frozen=True)
class GivenDamageModEvent(BuffEvent):
    value: IntValueModifier | FloatValueModifier


@dataclass
class BuffGivenDamage(BuffBase):
    """주는 대미지 증가/감소"""

    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ATTACK}

    def apply(self) -> GivenDamageModEvent:
        if self.value_type == BuffValueType.INTEGER:
            return GivenDamageModEvent(
                condition=self.condition, value=IntValueModifier(self.value)
            )
        elif self.value_type == BuffValueType.PERCENT:
            return GivenDamageModEvent(
                condition=self.condition, value=FloatValueModifier(self.value)
            )
        else:
            raise ValueError(self.value_type)
