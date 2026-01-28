import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.objects.buff.conditions import Condition
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.commands.models import CommandCalculator



@dataclass(frozen=True)
class BuffEvent(abc.ABC):
    condition: Optional[Condition]

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: CharacterId,
    ) -> bool:
        return self.condition.is_applied(context, holder, attacker_or_target)

    @abc.abstractmethod
    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: "BattlefieldContext",
        calculator: "CommandCalculator",
    ) -> None:
        pass
