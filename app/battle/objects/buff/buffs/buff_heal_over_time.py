from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.core.commands.models import HealCalculateData, HealData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueSourceType
from battle.objects.models import BaseValueIndicator, CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


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
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        calculator.data_by_effect[effect_seq_number].heal_data_list.append(
            HealCalculateData(
                HealData(
                    healer_id=attacker_or_target,
                    target_id=holder,
                    value=BaseValueIndicator(ValueSourceType.FIXED, self.value),
                ),
                [],
            )
        )


class BuffHealOverTime(BuffBase):
    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ROUND_END

    def create_event(self) -> HealOverTimeEvent:
        return HealOverTimeEvent(condition=self.condition, value=self.value)
