import abc
from dataclasses import KW_ONLY, dataclass, field
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.character.buffed_stats import BuffedStats
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import (
    CharacterId,
    DamageData,
    FloatValueModifier,
    HealData,
    IntValueModifier,
    MoveData,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.buff_events import BuffEvent


# user input -> parse() -> list[CommandBase] -> expand_xxx_command() ->
# list[CommandData] -> process_xxx_command() -> list[CommandProcessResult]


@dataclass(frozen=True)
class CharacterCommand:
    user_id: CharacterId
    parts: list["CommandPartBase"]


@dataclass(frozen=True)
class CommandPartBase(abc.ABC):
    pass


@dataclass(frozen=True)
class ActionCommandPart(CommandPartBase):
    type_: ActionType
    target_positions: Optional[list[BattlefieldColumnIndex]] = field(
        default_factory=list
    )
    target_characters: Optional[list[CharacterId]] = field(default_factory=list)


@dataclass(frozen=True)
class ItemCommandPart(CommandPartBase):
    item_name: str
    targets: Optional[list[CharacterId]]


@dataclass(frozen=True)
class CommandPartData:
    original_part: CommandPartBase

    _: KW_ONLY
    move_list: list[MoveData]
    damage_list: list[DamageData]
    heal_list: list[HealData]
    buff_add_list: list[BuffAddData]

    admin_target_phase: Optional[RoundPhaseType] = None


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


class CommandPartCalculator:
    def __init__(self, data: CommandPartData, context: "BattlefieldContext"):
        self.data = data
        self.context = context
        self.buffed_stats_by_character: dict[CharacterId, BuffedStats] = {
            char_id: BuffedStats(character.status, {})
            for char_id, character in context.characters.items()
        }

        self.ban_event_list: list[BuffEvent] = []
        self.damage_data_list: list[DamageCalculateData] = [
            DamageCalculateData(damage_data, []) for damage_data in data.damage_list
        ]
        self.heal_data_list: list[HealCalculateData] = [
            HealCalculateData(heal_data, []) for heal_data in data.heal_list
        ]


@dataclass(frozen=True)
class CommandPartProcessResult:
    original_part: CommandPartBase
    ban_result: Optional[BanResult] = None


@dataclass(frozen=True)
class CommandProcessResult:
    original_command: CharacterCommand
    part_results: list[CommandPartProcessResult]
