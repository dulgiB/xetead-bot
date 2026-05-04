from dataclasses import dataclass

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import (
    CommandPartCalculator,
    HealCalculateData,
    HealData,
)
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId


@dataclass(frozen=True)
class HealOverTimeEvent(BuffEvent):
    value: int

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: BattlefieldContext,
        calculator: CommandPartCalculator,
    ) -> None:
        calculator.heal_data_list.append(
            HealCalculateData(
                HealData(
                    healer_id=attacker_or_target, target_id=holder, value=self.value
                ),
                [],
            )
        )


class BuffHealOverTime(BuffBase):
    @property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ROUND_END}

    def create_event(self) -> HealOverTimeEvent:
        return HealOverTimeEvent(condition=self.condition, value=self.value)
