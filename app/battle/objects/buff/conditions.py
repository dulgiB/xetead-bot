import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.commands.models import CommandPartData


@dataclass(frozen=True)
class Condition(abc.ABC):
    value: Optional[int] = None

    @abc.abstractmethod
    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        pass


@dataclass(frozen=True)
class IsInSameColumnCondition(Condition):
    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if attacker_or_target is None:
            return False

        return context.find_character_position(
            holder
        ) == context.find_character_position(attacker_or_target)


@dataclass(frozen=True)
class WasNotAttackedCondition(Condition):
    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        for result in context.prev_round_results:
            if isinstance(result.command_data, CommandPartData) and holder in [
                data.target_id for data in result.command_data.damage_list
            ]:
                return False

        return True
