from dataclasses import dataclass

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import CommandPartCalculator, DamageData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId


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
        context: "BattlefieldContext",
        calculator: "CommandPartCalculator",
    ) -> None:
        for damage_data in calculator.damage_data_list:
            if damage_data.base.attacker_id == holder:
                damage_data.base = DamageData(
                    damage_data.base.attacker_id, self.taunter, damage_data.base.value
                )


class BuffTaunt(BuffBase):
    """도발"""

    @property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ACTION}

    def create_event(self) -> BuffEvent:
        return TauntedByEvent(condition=self.condition, taunter=self.given_by)
