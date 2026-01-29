from dataclasses import dataclass
from functools import cached_property

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
    def __init__(self, **kwargs):
        super(BuffDamageOverTime, self).__init__(**kwargs)
        self._value = self.value

    @cached_property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ROUND_END}

    def apply(self) -> DamageOverTimeEvent:
        return DamageOverTimeEvent(condition=self.condition, value=self.value)
