import abc
from dataclasses import KW_ONLY, dataclass, field
from typing import Optional

from battle.objects.buff.buff_base import BuffAddEvent, BuffRemoveEvent
from battle.objects.buff.buff_events import BanActionEvent
from battle.objects.define import ActionType, BattlefieldSlotIndex
from battle.objects.models import BaseValueIndicator, CharacterId

# user input -> parse() -> list[CommandBase] -> expand_xxx_command() ->
# list[CommandData] -> process_xxx_command() -> list[CommandProcessResult]


class CommandBase(abc.ABC):
    user: CharacterId


@dataclass(frozen=True)
class MoveCommand(CommandBase):
    user: CharacterId
    to_position: BattlefieldSlotIndex


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
    to_position: BattlefieldSlotIndex


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


class CommandData(abc.ABC):
    command: CommandBase


@dataclass(frozen=True)
class CharacterCommandData(CommandData):
    command: CommandBase

    _: KW_ONLY
    move_list: list[MoveData] = field(default_factory=list)
    damage_list: list[DamageData] = field(default_factory=list)
    heal_list: list[HealData] = field(default_factory=list)
    buff_add_list: list[BuffAddEvent] = field(default_factory=list)
    buff_remove_list: list[BuffRemoveEvent] = field(default_factory=list)


@dataclass(frozen=True)
class BanResult:
    is_banned: bool
    source: BanActionEvent


@dataclass(frozen=True)
class CommandProcessResult:
    command_data: CommandData
    ban_result: Optional[BanResult] = None
