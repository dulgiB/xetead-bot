from dataclasses import dataclass
from functools import cached_property

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming


@dataclass(frozen=True)
class NoHealEvent(BuffEvent):
    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.POST


class BuffNoHeal(BuffBase):
    @cached_property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_RECEIVE_HEAL}

    def apply(self) -> NoHealEvent:
        return NoHealEvent(condition=self.condition)
