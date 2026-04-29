from battle.admin_utils import (
    AdminCommand,
    ChangePhaseCommand,
)
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import (
    CharacterCommand,
    CommandPartData,
    DamageData,
    MoveData,
)
from battle.objects.define import ActionType, BattlefieldColumnIndex, ValueSourceType
from battle.objects.models import BaseValueIndicator, CharacterId


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


def expand_character_command(
    command: CharacterCommand, context: BattlefieldContext
) -> list[CommandPartData]:
    parts_list: list[CommandPartData] = []

    for part in command.parts:
        if part.type_ == ActionType.MOVE and part.targets is not None:
            parts_list.append(
                CommandPartData(
                    part,
                    move_list=[MoveData(command.user_id, part.targets[0])],
                    damage_list=[],
                    heal_list=[],
                    buff_add_list=[],
                )
            )

        elif part.type_ == ActionType.ATTACK and part.targets is not None:
            parts_list.append(
                CommandPartData(
                    part,
                    move_list=[],
                    damage_list=[
                        DamageData(
                            command.user_id,
                            part.targets[0],
                            BaseValueIndicator(ValueSourceType.STAT_ATK_ROLL),
                        )
                    ],
                    heal_list=[],
                    buff_add_list=[],
                )
            )

        elif part.type_ == ActionType.SKILL_1 or part.type_ == ActionType.SKILL_2:
            skill = context.characters[command.user_id].skills[part.type_]
            target_characters = skill.target_rule.get_targets(part.targets)

            for skill_effect in skill.data.effects:
                move_list, damage_list, heal_list, buff_add_list = skill_effect.expand(
                    context, command.user_id, target_characters
                )
                parts_list.append(
                    CommandPartData(
                        part,
                        move_list=move_list,
                        damage_list=damage_list,
                        heal_list=heal_list,
                        buff_add_list=buff_add_list,
                    )
                )

        else:
            raise ValueError(part)

    return parts_list
