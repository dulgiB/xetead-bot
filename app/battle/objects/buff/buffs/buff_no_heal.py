from dataclasses import dataclass

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import CommandCalculator
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId


@dataclass(frozen=True)
class NoHealEvent(BuffEvent):
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

        for heal_data in calculator.heal_data_list:
            if heal_data.base.target_id == holder:
                data_to_remove.append(heal_data)

        for heal_data in data_to_remove:
            calculator.heal_data_list.remove(heal_data)


class BuffNoHeal(BuffBase):
    @property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_RECEIVE_HEAL}

    def create_event(self) -> NoHealEvent:
        return NoHealEvent(condition=self.condition)
