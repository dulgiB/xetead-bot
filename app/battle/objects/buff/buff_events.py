import abc
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

from battle.objects.buff.conditions import Condition
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.commands.models import CommandCalculator


class BuffEventCalculatePriority(Enum):
    PRE = 1
    NORMAL = 2
    POST = 3


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

    @property
    @abc.abstractmethod
    def priority(self) -> BuffEventCalculatePriority:
        pass
