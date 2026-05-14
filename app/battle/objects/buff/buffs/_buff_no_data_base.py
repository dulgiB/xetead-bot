import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.commands.models import CommandPartCalculator


@dataclass(frozen=True)
class NoDataEvent(BuffEvent, abc.ABC):
    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.POST

    @abc.abstractmethod
    def _get_data_list(self, calculator: "CommandPartCalculator") -> list:
        pass

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: "BattlefieldContext",
        calculator: "CommandPartCalculator",
    ) -> None:
        data_list = self._get_data_list(calculator)
        to_remove = [d for d in data_list if d.base.target_id == holder]
        for d in to_remove:
            data_list.remove(d)


class BuffNoDataBase(BuffBase, abc.ABC):
    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION
