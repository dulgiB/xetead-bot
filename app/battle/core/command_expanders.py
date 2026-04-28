from battle.admin_utils import (
    AdminCommand,
    ChangePhaseCommand,
)
from battle.core.commands.models import (
    ActionCommandPart,
    CharacterCommand,
    CommandPartData,
    DamageData,
    ItemCommandPart,
    MoveData,
)
from battle.objects.define import ActionType, ValueSourceType
from battle.objects.models import BaseValueIndicator


def expand_admin_command(command: AdminCommand) -> CommandPartData:
    if isinstance(command, ChangePhaseCommand):
        return CommandPartData(
            original_part=command,
            admin_target_phase=command.target_phase,
            move_list=[],
            damage_list=[],
            heal_list=[],
            buff_add_list=[],
        )
    else:
        raise TypeError(command)


def expand_character_command(command: CharacterCommand) -> list[CommandPartData]:
    parts_list: list[CommandPartData] = []
    for part in command.parts:
        if isinstance(part, ActionCommandPart):
            if part.type_ == ActionType.MOVE and part.target_positions is not None:
                parts_list.append(
                    CommandPartData(
                        part,
                        move_list=[MoveData(command.user_id, part.target_positions[0])],
                        damage_list=[],
                        heal_list=[],
                        buff_add_list=[],
                    )
                )

            if part.type_ == ActionType.ATTACK and part.target_characters is not None:
                parts_list.append(
                    CommandPartData(
                        part,
                        move_list=[],
                        damage_list=[
                            DamageData(
                                command.user_id,
                                part.target_characters[0],
                                BaseValueIndicator(ValueSourceType.STAT_ATK_ROLL),
                            )
                        ],
                        heal_list=[],
                        buff_add_list=[],
                    )
                )
            else:
                parts_list.append(
                    CommandPartData(
                        part,
                        move_list=[],
                        damage_list=[],
                        heal_list=[],
                        buff_add_list=[],
                    )
                )

        elif isinstance(command, ItemCommandPart):
            parts_list.append(
                CommandPartData(
                    part,
                    move_list=[],
                    damage_list=[],
                    heal_list=[],
                    buff_add_list=[],
                )
            )

        else:
            raise ValueError(part)

    return parts_list
