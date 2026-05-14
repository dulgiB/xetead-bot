from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buffs._buff_no_data_base import BuffNoDataBase, NoDataEvent

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class NoHealEvent(NoDataEvent):
    def _get_data_list(self, calculator: "CommandPartCalculator", effect_seq_number: int) -> list:
        return calculator.data_by_effect[effect_seq_number].heal_data_list


class BuffNoHeal(BuffNoDataBase):
    def create_event(self) -> NoHealEvent:
        return NoHealEvent(condition=self.condition)
