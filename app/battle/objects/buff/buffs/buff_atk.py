from dataclasses import dataclass

from battle.objects.buff.buff_base import BuffBase, BuffValueType
from battle.objects.define import BuffApplyTiming
from battle.objects.models import FloatValueModifier, IntValueModifier
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority


@dataclass(frozen=True)
class AtkModEvent(BuffEvent):
    value: IntValueModifier | FloatValueModifier

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

@dataclass
class BuffAtk(BuffBase):
    """공격력 증가/감소"""

    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ATTACK}

    def apply(self) -> AtkModEvent:
        if self.value_type == BuffValueType.INTEGER:
            return AtkModEvent(
                condition=self.condition,
                value=IntValueModifier(self.value),
            )
        elif self.value_type == BuffValueType.PERCENT:
            return AtkModEvent(
                condition=self.condition,
                value=FloatValueModifier(self.value),
            )
        else:
            raise ValueError(self.value_type)
