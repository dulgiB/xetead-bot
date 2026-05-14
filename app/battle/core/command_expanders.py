from typing import Optional

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
    CommandPartDataPerEffect,
    DamageData,
    MoveData,
)
from battle.exceptions import CommandValidationError, error_invalid_command_format
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import (
    ActionType,
    BuffApplyTiming,
    ValueSourceType,
)
from battle.objects.models import BaseValueIndicator, BuffUid, CharacterId, HealData


def expand_admin_command(
    command: AdminCommand, context: BattlefieldContext
) -> CommandPartData:
    if isinstance(command, ChangePhaseCommand):
        return CommandPartData(
            original_part=command,
            admin_target_phase=command.target_phase,
        )
    elif isinstance(command, ForceMoveCommand):
        return CommandPartData(
            original_part=command,
            data_per_effect=(
                CommandPartDataPerEffect(
                    move_list=[
                        MoveData(character_id=target, to_position=command.to_position)
                        for target in command.targets
                    ]
                ),
            ),
        )
    elif isinstance(command, ForceDamageCommand):
        return CommandPartData(
            original_part=command,
            data_per_effect=(
                CommandPartDataPerEffect(
                    damage_list=[
                        DamageData(
                            attacker_id=ADMIN_ID,
                            target_id=target,
                            value=BaseValueIndicator(
                                value_source=ValueSourceType.FIXED,
                                value=command.damage_value,
                            ),
                        )
                        for target in command.targets
                    ]
                ),
            ),
        )
    elif isinstance(command, ForceHealCommand):
        return CommandPartData(
            original_part=command,
            data_per_effect=(
                CommandPartDataPerEffect(
                    heal_list=[
                        HealData(
                            healer_id=ADMIN_ID,
                            target_id=target,
                            value=BaseValueIndicator(
                                value_source=ValueSourceType.FIXED,
                                value=command.heal_value,
                            ),
                        )
                        for target in command.targets
                    ]
                ),
            ),
        )
    elif isinstance(command, ForceAddBuffByIdCommand):
        return CommandPartData(
            original_part=command,
            data_per_effect=(
                CommandPartDataPerEffect(
                    buff_add_list=[
                        BuffAddData(
                            given_by=ADMIN_ID,
                            applied_to=target,
                            buff_id=command.buff_id,
                        )
                        for target in command.targets
                    ]
                ),
            ),
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
            admin_buff_remove_list=buff_remove_list,
        )
    else:
        raise TypeError(command)


def _get_taunt_override(
    user_id: CharacterId, context: BattlefieldContext
) -> Optional[CharacterId]:
    for buff in context.buff_container.get_buffs_by(user_id, BuffApplyTiming.ON_ACTION):
        override = buff.get_target_override()
        if override is not None:
            return override
    return None


def expand_character_command(
    command: CharacterCommand, context: BattlefieldContext
) -> list[CommandPartData]:
    parts_list: list[CommandPartData] = []
    taunted_target = _get_taunt_override(command.user_id, context)

    for part in command.parts:
        if part.type_ == ActionType.MOVE and part.targets is not None:
            parts_list.append(
                CommandPartData(
                    part,
                    data_per_effect=(
                        CommandPartDataPerEffect(
                            move_list=[MoveData(command.user_id, part.targets[0])]
                        ),
                    ),
                )
            )

        elif part.type_ == ActionType.ATTACK and part.targets is not None:
            effective_target = (
                taunted_target if taunted_target is not None else part.targets[0]
            )
            is_magic_attack = context.characters[
                command.user_id
            ].status.is_magic_attacker
            parts_list.append(
                CommandPartData(
                    part,
                    data_per_effect=(
                        CommandPartDataPerEffect(
                            damage_list=[
                                DamageData(
                                    command.user_id,
                                    effective_target,
                                    BaseValueIndicator(ValueSourceType.STAT_ATK_ROLL),
                                    is_magic_attack,
                                )
                            ]
                        ),
                    ),
                )
            )

        elif part.type_ == ActionType.SKILL:
            skill_used = None
            for skill in context.characters[command.user_id].skills:
                if skill.data.id == part.skill_id:
                    skill_used = skill
                    break

            if skill_used is None:
                break

            if (
                taunted_target is not None
                and not skill_used.target_rule.ignores_input_targets
            ):
                target_characters = [taunted_target]
            else:
                target_characters = skill_used.target_rule.get_targets(part.targets)

            data_per_effect_list: list[CommandPartDataPerEffect] = []

            for skill_effect in skill_used.data.effects:
                move_list, damage_list, heal_list, buff_add_list = skill_effect.expand(
                    context, command.user_id, target_characters
                )
                data_per_effect_list.append(
                    CommandPartDataPerEffect(
                        move_list=move_list,
                        damage_list=damage_list,
                        heal_list=heal_list,
                        buff_add_list=buff_add_list,
                    )
                )

            parts_list.append(
                CommandPartData(
                    original_part=part, data_per_effect=tuple(data_per_effect_list)
                )
            )

        else:
            raise CommandValidationError(error_invalid_command_format())

    return parts_list
