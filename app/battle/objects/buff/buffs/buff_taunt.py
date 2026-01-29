from dataclasses import dataclass

from battle.objects.buff.buff_events import BuffEvent
from battle.objects.models import CharacterId


@dataclass(frozen=True)
class TauntedByEvent(BuffEvent):
    target: CharacterId
class BuffTaunt(BuffBase):
    """도발"""

    @property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ATTACK}

    def apply(self) -> BuffEvent:
        return TauntedByEvent(condition=self.condition, taunter=self.given_by)
