from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import (
    ADMIN_ID,
    AdminCommand,
    ChangePhaseCommand,
    ForceAddBuffByIdCommand,
    ForceDamageCommand,
    ForceHealCommand,
    ForceMoveCommand,
    ForceRemoveBuffByIdCommand,
)
from battle.core.commands.models import (
    CharacterCommand,
    CommandPartData,
    DamageData,
    MoveData,
)
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import ActionType, BattlefieldColumnIndex, ValueSourceType
from battle.objects.models import BaseValueIndicator, BuffUid, CharacterId, HealData


def expand_admin_command(
    command: AdminCommand, context: BattlefieldContext
) -> CommandPartData:
    if isinstance(command, ChangePhaseCommand):
        return CommandPartData(
            original_part=command,
            admin_target_phase=command.target_phase,
            move_list=[],
            damage_list=[],
            heal_list=[],
            buff_add_list=[],
        )
    elif isinstance(command, ForceMoveCommand):
        return CommandPartData(
            original_part=command,
            move_list=[
                MoveData(character_id=target, to_position=command.to_position)
                for target in command.targets
            ],
            damage_list=[],
            heal_list=[],
            buff_add_list=[],
        )
    elif isinstance(command, ForceDamageCommand):
        return CommandPartData(
            original_part=command,
            move_list=[],
            damage_list=[
                DamageData(
                    attacker_id=ADMIN_ID, target_id=target, value=command.damage_value
                )
                for target in command.targets
            ],
            heal_list=[],
            buff_add_list=[],
        )
    elif isinstance(command, ForceHealCommand):
        return CommandPartData(
            original_part=command,
            move_list=[],
            damage_list=[],
            heal_list=[
                HealData(healer_id=ADMIN_ID, target_id=target, value=command.heal_value)
                for target in command.targets
            ],
            buff_add_list=[],
        )
    elif isinstance(command, ForceAddBuffByIdCommand):
        return CommandPartData(
            original_part=command,
            move_list=[],
            damage_list=[],
            heal_list=[],
            buff_add_list=[
                BuffAddData(
                    given_by=ADMIN_ID,
                    applied_to=target,
                    buff_id=command.buff_id,
                )
                for target in command.targets
            ],
        )
    elif isinstance(command, ForceRemoveBuffByIdCommand):
        buff_remove_list: list[BuffUid] = []
        for target in command.targets:
            target_buff_list = context.buff_container.get_buffs_by(target, None)
            buff_remove_list.extend(
                buff.uid for buff in target_buff_list if buff.id == command.buff_id
            )
        return CommandPartData(
            original_part=command,
            move_list=[],
            damage_list=[],
            heal_list=[],
            buff_add_list=[],
            admin_buff_remove_list=buff_remove_list,
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
