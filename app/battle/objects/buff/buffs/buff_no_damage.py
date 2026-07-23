from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buffs._buff_no_data_base import BuffNoDataBase, NoDataEvent

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class NoDamageEvent(NoDataEvent):
    @property
    def _effect_label(self) -> str:
        return "대미지"

    def _get_data_list(
        self, calculator: "CommandPartCalculator", effect_seq_number: int
    ) -> list:
        return calculator.data_by_effect[effect_seq_number].damage_data_list


class BuffNoDamage(BuffNoDataBase):
    def create_event(self) -> NoDamageEvent:
        return NoDamageEvent(
            condition=self.condition, buff_label=self.display_id_label()
        )
