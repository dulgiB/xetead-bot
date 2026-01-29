from dataclasses import dataclass
from functools import cached_property

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent
from battle.objects.define import BuffApplyTiming


@dataclass(frozen=True)
class NoDamageEvent(BuffEvent):
    pass


class BuffNoDamage(BuffBase):
    @cached_property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_HIT}

    def apply(self) -> NoDamageEvent:
        return NoDamageEvent(
            condition=self.condition,
        )
