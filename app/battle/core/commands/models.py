from dataclasses import KW_ONLY, dataclass, field
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.character.buffed_stats import BuffedStats
from battle.objects.define import ActionType, BattlefieldColumnIndex, CombatStatType
from battle.objects.models import (
    BuffUid,
    CharacterId,
    DamageData,
    HealData,
    MoveData,
    ValueModifierBase,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.buff_events import BuffEvent


# user input -> parse() -> list[CommandBase] -> expand_xxx_command() ->
# list[CommandData] -> process_xxx_command() -> list[CommandProcessResult]


@dataclass(frozen=True)
class CharacterCommand:
    user_id: CharacterId
    parts: list["CommandPart"]


@dataclass(frozen=True)
class CommandPart:
    type_: ActionType

    _: KW_ONLY
    targets: list[CharacterId] | list[BattlefieldColumnIndex] = field(
        default_factory=list
    )
    item_name: Optional[str] = None


@dataclass(frozen=True)
class CommandPartData:
    original_part: CommandPart

    _: KW_ONLY
    move_list: list[MoveData]
    damage_list: list[DamageData]
    heal_list: list[HealData]
    buff_add_list: list[BuffAddData]

    admin_target_phase: Optional[RoundPhaseType] = None
    admin_buff_remove_list: list[BuffUid] = None


@dataclass(frozen=True)
class BanResult:
    is_banned: bool
    source: "BuffEvent"


@dataclass
class DamageCalculateData:
    base: DamageData
    modifiers: list[ValueModifierBase]


@dataclass
class HealCalculateData:
    base: HealData
    modifiers: list[ValueModifierBase]


class CommandPartCalculator:
    def __init__(self, data: CommandPartData, context: "BattlefieldContext"):
        self.data = data
        self.context = context
        self.buffed_stats_by_character: dict[CharacterId, BuffedStats] = {
            char_id: BuffedStats(
                character.status, {stat: [] for stat in CombatStatType}
            )
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
    original_part: CommandPart
    expanded_part: CommandPartData
    ban_result: Optional[BanResult] = None


@dataclass(frozen=True)
class CommandProcessResult:
    original_command: CharacterCommand
    part_results: list[CommandPartProcessResult]
