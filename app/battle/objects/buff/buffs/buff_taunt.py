from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class TauntedByEvent(BuffEvent):
    taunter: CharacterId

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.POST

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        pass


class BuffTaunt(BuffBase):
    """도발"""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> BuffEvent:
        return TauntedByEvent(condition=self.condition, taunter=self.given_by)

    def get_target_override(self) -> Optional[CharacterId]:
        return self.given_by
