from dataclasses import dataclass

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import (
    CommandCalculator,
    DamageCalculateData,
    DamageData,
)
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId


@dataclass(frozen=True)
class DamageOverTimeEvent(BuffEvent):
    value: int

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: BattlefieldContext,
        calculator: CommandCalculator,
    ) -> None:
        calculator.damage_data_list.append(
            DamageCalculateData(
                DamageData(
                    attacker_id=attacker_or_target,
                    target_id=holder,
                    value=self.value,
                ),
                [],
            )
        )


class BuffDamageOverTime(BuffBase):
    @property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ROUND_END}

    def create_event(self) -> DamageOverTimeEvent:
        return DamageOverTimeEvent(condition=self.condition, value=self.value)
