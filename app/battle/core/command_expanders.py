from battle.admin_utils import (
    AdminCommandData,
    ChangePhaseCommand,
    ChangePhaseCommandData,
)
from battle.core.commands.models import (
    ActionCommand,
    CharacterCommandData,
    CommandBase,
    DamageData,
    ItemCommand,
    MoveCommand,
    MoveData,
)
from battle.objects.define import ActionType, ValueSourceType
from battle.objects.models import BaseValueIndicator


def expand_admin_command(command: CommandBase) -> AdminCommandData:
    if isinstance(command, ChangePhaseCommand):
        return ChangePhaseCommandData(command.target_phase)
    else:
        raise TypeError(command)


def expand_character_command(command: CommandBase) -> CharacterCommandData:
    if isinstance(command, MoveCommand):
        return CharacterCommandData(
            command,
            move_list=[MoveData(command.user, command.to_position)],
            damage_list=[],
            heal_list=[],
            buff_add_list=[],
            buff_remove_list=[],
        )

    elif isinstance(command, ActionCommand):
        if command.type_ == ActionType.ATTACK:
            return CharacterCommandData(
                command,
                move_list=[],
                damage_list=[
                    DamageData(
                        command.user,
                        command.targets[0],
                        BaseValueIndicator(ValueSourceType.STAT_ATK_ROLL),
                    )
                ],
                heal_list=[],
                buff_add_list=[],
                buff_remove_list=[],
            )
        else:
            return CharacterCommandData(
                command,
                move_list=[],
                damage_list=[],
                heal_list=[],
                buff_add_list=[],
                buff_remove_list=[],
            )

    elif isinstance(command, ItemCommand):
        return CharacterCommandData(
            command,
            move_list=[],
            damage_list=[],
            heal_list=[],
            buff_add_list=[],
            buff_remove_list=[],
        )

    else:
        raise ValueError(command)
