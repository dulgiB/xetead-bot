import abc
from dataclasses import KW_ONLY, dataclass
from typing import TYPE_CHECKING, Optional

from battle.objects.buff.buff_base import BuffAddEvent, BuffRemoveEvent
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    FloatValueModifier,
    IntValueModifier,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.buff_events import BuffEvent
    from battle.objects.character.buffed_stats import BuffedStats


# user input -> parse() -> list[CommandBase] -> expand_xxx_command() ->
# list[CommandData] -> process_xxx_command() -> list[CommandProcessResult]


class CommandBase(abc.ABC):
    user: CharacterId


@dataclass(frozen=True)
class MoveCommand(CommandBase):
    user: CharacterId
    to_position: BattlefieldColumnIndex


@dataclass(frozen=True)
class ActionCommand(CommandBase):
    user: CharacterId
    type_: ActionType
    targets: Optional[list[CharacterId]]


@dataclass(frozen=True)
class ItemCommand(CommandBase):
    user: CharacterId
    item_name: str
    targets: Optional[list[CharacterId]]


@dataclass(frozen=True)
class MoveData:
    character_id: CharacterId
    to_position: BattlefieldColumnIndex


@dataclass(frozen=True)
class DamageData:
    attacker_id: CharacterId
    target_id: CharacterId
    value: int | BaseValueIndicator


@dataclass(frozen=True)
class HealData:
    healer_id: CharacterId
    target_id: CharacterId
    value: int | BaseValueIndicator


@dataclass(frozen=True)
class CommandData:
    command: CommandBase

    _: KW_ONLY
    move_list: list[MoveData]
    damage_list: list[DamageData]
    heal_list: list[HealData]
    buff_add_list: list[BuffAddEvent]
    buff_remove_list: list[BuffRemoveEvent]


@dataclass(frozen=True)
class BanResult:
    is_banned: bool
    source: "BuffEvent"


@dataclass
class DamageCalculateData:
    base: DamageData
    modifiers: list[IntValueModifier | FloatValueModifier]


@dataclass
class HealCalculateData:
    base: HealData
    modifiers: list[IntValueModifier | FloatValueModifier]


class CommandCalculator:
    def __init__(self, command_data: CommandData, context: "BattlefieldContext"):
        self.command_data = command_data
        self.context = context
        self.buffed_stats_by_character: dict[CharacterId, BuffedStats] = {
            char_id: BuffedStats(character.status, {})
            for char_id, character in context.characters.items()
        }

        self.ban_event_list: list[BuffEvent] = []
        self.damage_data_list: list[DamageCalculateData] = [
            DamageCalculateData(data, []) for data in command_data.damage_list
        ]
        self.heal_data_list: list[HealCalculateData] = [
            HealCalculateData(data, []) for data in command_data.heal_list
        ]


@dataclass(frozen=True)
class CommandProcessResult:
    command_data: CommandData
    ban_result: Optional[BanResult] = None
