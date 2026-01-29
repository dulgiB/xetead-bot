from dataclasses import dataclass
from functools import cached_property

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import CommandCalculator
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId


@dataclass(frozen=True)
class NoDamageEvent(BuffEvent):
    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.POST

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: BattlefieldContext,
        calculator: CommandCalculator,
    ) -> None:
        data_to_remove = []

        for damage_data in calculator.damage_data_list:
            if damage_data.base.target_id == holder:
                data_to_remove.append(damage_data)

        for damage_data in data_to_remove:
            calculator.damage_data_list.remove(damage_data)


class BuffNoDamage(BuffBase):
    @cached_property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_HIT}

    def apply(self) -> NoDamageEvent:
        return NoDamageEvent(
            condition=self.condition,
        )
