from dataclasses import replace
from typing import TYPE_CHECKING, cast

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
    FateBoostMode,
    ValueSourceType,
)
from battle.objects.models import BaseValueIndicator, BuffUid, CharacterId, HealData
from battle.objects.skill.target_functions import (
    SkillTargetRule,
    SkillTargetRuleAllyColumn,
    SkillTargetRuleColumn,
    SkillTargetRuleColumnRange,
)

if TYPE_CHECKING:
    from battle.objects.skill.models import SkillData


def _mark_ignores_taunt_if_column_target(
    target_rule: SkillTargetRule, damage_list: list[DamageData]
) -> list[DamageData]:
    """열 광역 target rule(SkillTargetRuleColumn/AllyColumn/ColumnRange)로
    생성된 대미지는 도발 리다이렉트를 적용하지 않는다 — 열에 있는 각 대상이
    "이동해서 벗어날지, 맞고 버틸지"를 개별적으로 판단해야 하는 설계라,
    도발이 적용되면 열 전체 대미지가 도발자 한 명에게 몰려 그 설계가
    무너진다."""
    if not isinstance(
        target_rule,
        (SkillTargetRuleColumn, SkillTargetRuleAllyColumn, SkillTargetRuleColumnRange),
    ):
        return damage_list
    return [replace(damage, ignores_taunt=True) for damage in damage_list]


def _apply_fate_buff_boost(
    skill_data: "SkillData",
    data_per_effect_list: list[CommandPartDataPerEffect],
    context: BattlefieldContext,
) -> None:
    """운명간섭("+")의 버프 강화 모드를 부여 예정인 버프에 반영한다.

    대미지/회복 보정(굴림 보정·수치 강화)과 달리 버프는 계산 단계에 수치가
    없으므로, 부여 데이터를 만드는 이 시점에 얹어야 한다. 설정 오류(모드에
    맞지 않는 효과 등)는 전투 개시 시점 검증(fate_config_error)이 admin에게
    미리 알리므로, 여기서는 조용히 원래 버프를 그대로 둔다.
    """
    mode = skill_data.fate_mode
    if mode not in (FateBoostMode.BUFF_VALUE_BOOST, FateBoostMode.BUFF_STACK_BOOST):
        return
    index = skill_data.fate_effect_index
    if not (0 <= index < len(data_per_effect_list)):
        return

    bonus = skill_data.fate_boost_value
    buff_add_list = data_per_effect_list[index].buff_add_list
    for i, buff_add in enumerate(buff_add_list):
        if mode is FateBoostMode.BUFF_STACK_BOOST:
            buff_add_list[i] = replace(
                buff_add, stack_value=buff_add.stack_value + bonus
            )
            continue
        # 다른 효과가 이미 스냅샷해 둔 수치가 있으면 그쪽을 기준으로 삼는다.
        base_value = (
            buff_add.value_override
            if buff_add.value_override is not None
            else context.get_buff_data_by_id(buff_add.buff_id).value
        )
        buff_add_list[i] = replace(buff_add, value_override=base_value + bonus)


def expand_admin_command(
    command: AdminCommand, context: BattlefieldContext
) -> CommandPartData:
    if isinstance(command, ChangePhaseCommand):
        return CommandPartData(
            original_part=command,
            admin_target_phase=command.target_phase,
        )
    elif isinstance(command, ForceMoveCommand):
        # Force* 커맨드의 targets는 항상 캐릭터 이름뿐이다(열은 to_position 담당).
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
    # 도발/희생 방어 치환은 CommandPartCalculator가 일괄 처리한다 —
    # 여기서는 원래 지정 대상 그대로 전개한다.
    parts_list: list[CommandPartData] = []

    for part in command.parts:
        if part.type_ == ActionType.MOVE and part.targets is not None:
            # parser.py가 이동 커맨드에는 항상 열 하나만 채워 넣는다.
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
            # parser.py가 공격 커맨드에는 항상 캐릭터 이름 하나만 채워 넣는다.
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
                # expand()가 즉시 부수효과를 일으키므로 그 전에 확정해야 한다.
                debuff_clear_list = skill_effect.get_debuff_clear_targets(
                    context, target_characters
                )
                move_list, damage_list, heal_list, buff_add_list, buff_remove_list = (
                    skill_effect.expand(
                        context, command.user_id, target_characters, raw_targets
                    )
                )
                damage_list = _mark_ignores_taunt_if_column_target(
                    skill_used.target_rule, damage_list
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

            if part.fate_boost:
                _apply_fate_buff_boost(skill_used.data, data_per_effect_list, context)

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

            # 효과 없는 아이템은 try_expansion_if_valid()가 이미 걸러냈다.
            assert item_used.data.effect is not None
            debuff_clear_list = item_used.data.effect.get_debuff_clear_targets(
                context, target_characters
            )
            move_list, damage_list, heal_list, buff_add_list, buff_remove_list = (
                item_used.data.effect.expand(
                    context, command.user_id, target_characters
                )
            )
            damage_list = _mark_ignores_taunt_if_column_target(
                item_used.target_rule, damage_list
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
