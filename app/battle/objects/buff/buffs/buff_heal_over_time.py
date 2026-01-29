from dataclasses import dataclass
from functools import cached_property

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent
from battle.objects.define import BuffApplyTiming


@dataclass(frozen=True)
class HealOverTimeEvent(BuffEvent):
    value: int


class BuffHealOverTime(BuffBase):
    def __init__(self, **kwargs):
        super(BuffHealOverTime, self).__init__(**kwargs)
        self._value = self.value

    @cached_property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ROUND_END}

    def apply(self) -> HealOverTimeEvent:
        return HealOverTimeEvent(condition=self.condition, value=self.value)
