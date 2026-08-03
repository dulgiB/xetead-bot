from typing import cast

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
from battle.exceptions import (
    CommandValidationError,
    error_invalid_command_format,
    error_skill_not_registered,
)
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
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
        # Admin의 Force* 커맨드는 항상 캐릭터 이름만 대상으로 받는다(열
        # 지정은 to_position 필드가 별도로 담당) — command_expanders.py 상단
        # 주석 참고.
        move_targets = cast(list[CharacterId], command.targets)
        return CommandPartData(
            original_part=command,
            data_per_effect=(
                CommandPartDataPerEffect(
                    move_list=[
                        MoveData(
                            character_id=target,
                            to_position=command.to_position,
                            is_forced=True,
                        )
                        for target in move_targets
                    ]
                ),
            ),
        )
    elif isinstance(command, ForceDamageCommand):
        damage_targets = cast(list[CharacterId], command.targets)
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
                        for target in damage_targets
                    ]
                ),
            ),
        )
    elif isinstance(command, ForceHealCommand):
        heal_targets = cast(list[CharacterId], command.targets)
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
                        for target in heal_targets
                    ]
                ),
            ),
        )
    elif isinstance(command, ForceAddBuffByIdCommand):
        buff_add_targets = cast(list[CharacterId], command.targets)
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
                        for target in buff_add_targets
                    ]
                ),
            ),
        )
    elif isinstance(command, ForceRemoveBuffByIdCommand):
        buff_remove_list: list[BuffUid] = []
        for target in cast(list[CharacterId], command.targets):
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


def expand_character_command(
    command: CharacterCommand,
    context: BattlefieldContext,
) -> list[CommandPartData]:
    # 도발/희생 방어에 의한 대상 치환은 대미지 처리 시점(CommandPartCalculator)에서
    # 일괄 수행한다. 여기서는 원래 지정 대상으로 전개만 한다.
    parts_list: list[CommandPartData] = []

    for part in command.parts:
        if part.type_ == ActionType.MOVE and part.targets is not None:
            # parser.py의 command_format_move가 이동 커맨드에는 항상 열
            # 하나만 targets[0]에 채워 넣는다.
            move_pos = cast(BattlefieldColumnIndex, part.targets[0])
            parts_list.append(
                CommandPartData(
                    part,
                    data_per_effect=(
                        CommandPartDataPerEffect(
                            move_list=[MoveData(command.user_id, move_pos)]
                        ),
                    ),
                )
            )

        elif part.type_ == ActionType.ATTACK and part.targets is not None:
            is_magic_attack = context.characters[
                command.user_id
            ].status.is_magic_attacker
            # parser.py의 command_format_attack이 공격 커맨드에는 항상 캐릭터
            # 이름 하나만 targets[0]에 채워 넣는다.
            attack_target = cast(CharacterId, part.targets[0])
            parts_list.append(
                CommandPartData(
                    part,
                    data_per_effect=(
                        CommandPartDataPerEffect(
                            damage_list=[
                                DamageData(
                                    command.user_id,
                                    attack_target,
                                    BaseValueIndicator(ValueSourceType.STAT_ATK_ROLL),
                                    is_magic_attack,
                                )
                            ]
                        ),
                    ),
                )
            )

        elif part.type_ == ActionType.SKILL:
            assert (
                part.skill_id is not None
            )  # ActionType.SKILL이면 parser.py가 항상 채움
            skill_used = None
            for skill in context.characters[command.user_id].skills:
                if skill.data.id == part.skill_id:
                    skill_used = skill
                    break

            if skill_used is None:
                raise CommandValidationError(error_skill_not_registered(part.skill_id))

            target_characters = skill_used.target_rule.get_targets(part.targets)
            raw_targets = tuple(part.targets)

            data_per_effect_list: list[CommandPartDataPerEffect] = []

            for skill_effect in skill_used.data.effects:
                # expand()가 즉시 부수효과(디버프 일괄 제거 등)를 일으킬 수 있으므로,
                # "무엇이 지워질지"는 expand() 호출 전에 먼저 확정해야 한다.
                debuff_clear_list = skill_effect.get_debuff_clear_targets(
                    context, target_characters
                )
                move_list, damage_list, heal_list, buff_add_list, buff_remove_list = (
                    skill_effect.expand(
                        context, command.user_id, target_characters, raw_targets
                    )
                )
                data_per_effect_list.append(
                    CommandPartDataPerEffect(
                        move_list=move_list,
                        damage_list=damage_list,
                        heal_list=heal_list,
                        buff_add_list=buff_add_list,
                        buff_remove_list=buff_remove_list,
                        debuff_clear_list=debuff_clear_list,
                        apply_timing=skill_effect.apply_timing,
                    )
                )

            parts_list.append(
                CommandPartData(
                    original_part=part, data_per_effect=tuple(data_per_effect_list)
                )
            )

        elif part.type_ == ActionType.USE_ITEM and part.item_id is not None:
            item_used = context.get_item_data_by_id(part.item_id).to_item_instance(
                context, command.user_id
            )

            target_characters = item_used.target_rule.get_targets(part.targets)

            debuff_clear_list = item_used.data.effect.get_debuff_clear_targets(
                context, target_characters
            )
            move_list, damage_list, heal_list, buff_add_list, buff_remove_list = (
                item_used.data.effect.expand(
                    context, command.user_id, target_characters
                )
            )

            parts_list.append(
                CommandPartData(
                    original_part=part,
                    data_per_effect=(
                        CommandPartDataPerEffect(
                            move_list=move_list,
                            damage_list=damage_list,
                            heal_list=heal_list,
                            buff_add_list=buff_add_list,
                            buff_remove_list=buff_remove_list,
                            debuff_clear_list=debuff_clear_list,
                            apply_timing=item_used.data.effect.apply_timing,
                        ),
                    ),
                )
            )

        else:
            raise CommandValidationError(error_invalid_command_format())

    return parts_list
