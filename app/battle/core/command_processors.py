from typing import TYPE_CHECKING, Optional

from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_expanders import expand_character_command
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import (
    BanResult,
    CharacterCommand,
    CommandPartCalculator,
    CommandPartData,
    CommandPartProcessResult,
    CommandProcessResult,
)
from battle.exceptions import (
    CommandValidationError,
    error_attack_position_too_far,
    error_no_remaining_cost,
    error_target_does_not_exist,
    error_too_many_characters,
)
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.buffs.buff_ban_action import BanActionEvent
from battle.objects.define import BuffApplyTiming, CombatStatType
from battle.objects.extensions import get_bonus_damage, get_total_cost
from battle.objects.models import CharacterId, DamageData, HealData, ValueWithModifiers
from utils.battle_helpers import is_reachable

if TYPE_CHECKING:
    from battle.core.round_manager import RoundManager


def process_admin_command(
    round_manager: "RoundManager", expanded_command: CommandPartData
) -> None:
    if expanded_command.admin_target_phase:
        round_manager.to_phase(expanded_command.admin_target_phase)
        return

    for move_data in expanded_command.move_list:
        round_manager._context.move_character_to(
            move_data.character_id, move_data.to_position
        )

    for damage_data in expanded_command.damage_list:
        round_manager._context.apply_damage(
            damage_data.attacker_id,
            damage_data.target_id,
            ValueWithModifiers(damage_data.value, []),
            None,
        )

    for heal_data in expanded_command.heal_list:
        round_manager._context.apply_heal(
            heal_data.healer_id,
            heal_data.target_id,
            ValueWithModifiers(heal_data.value, []),
            None,
        )

    for buff_add_event in expanded_command.buff_add_list:
        round_manager._context.buff_container.add(buff_add_event)

    for buff_to_remove in expanded_command.admin_buff_remove_list:
        round_manager._context.buff_container.remove(buff_to_remove)


def process_ally_command(
    context: BattlefieldContext, command: CharacterCommand
) -> CommandProcessResult:
    # 사전 검증 - 문제 있으면 여기서 raise
    maybe_expanded_parts, needed_cost = try_expansion_if_valid(context, command)
    if not maybe_expanded_parts:
        return CommandProcessResult(original_command=command, part_results=[])

    results_per_part: list[CommandPartProcessResult] = []

    for part_data in maybe_expanded_parts:
        calculator = CommandPartCalculator(part_data, context)

        # 행동 가능 여부 체크
        ban_results = _get_ban_results(calculator, context, command.user_id)
        maybe_ban_result: Optional[BanResult] = None
        for ban_result in ban_results:
            if ban_result.is_banned:
                maybe_ban_result = ban_result
                break
        if maybe_ban_result:
            results_per_part.append(
                CommandPartProcessResult(
                    expanded_part=part_data,
                    ban_result=maybe_ban_result,
                )
            )
            continue

        # 이동 처리
        for move_data in calculator.move_list:
            context.move_character_to(move_data.character_id, move_data.to_position)

        _process_damage(calculator, context)
        _process_heal(calculator, context)

        # 버프 추가
        for buff_add_event in part_data.buff_add_list:
            context.buff_container.add(buff_add_event)

        results_per_part.append(
            CommandPartProcessResult(
                expanded_part=part_data,
                ban_result=None,
            )
        )

    print(results_per_part)

    # 코스트 차감 - 검증 통과 후 실제 처리 시점에 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    return CommandProcessResult(original_command=command, part_results=results_per_part)


# Pre-action에서는 이동과 PRE 타이밍 버프 부여를 처리
def process_enemy_command_on_pre_action(
    context: BattlefieldContext,
    command: CharacterCommand,
    remaining_parts_dict: dict[CharacterId, list[DamageData | HealData | BuffAddData]],
) -> CommandProcessResult:
    # 사전 검증 - 문제 있으면 여기서 raise
    maybe_expanded_parts, needed_cost = try_expansion_if_valid(context, command)
    if not maybe_expanded_parts:
        return CommandProcessResult(original_command=command, part_results=[])

    remaining_parts_dict[command.user_id] = []
    results_per_part: list[CommandPartProcessResult] = []

    for part_data in maybe_expanded_parts:
        calculator = CommandPartCalculator(part_data, context)

        # 행동 가능 여부 체크
        ban_results = _get_ban_results(calculator, context, command.user_id)

        maybe_ban_result: Optional[BanResult] = None
        for ban_result in ban_results:
            if ban_result.is_banned:
                maybe_ban_result = ban_result
                break
        if maybe_ban_result:
            results_per_part.append(
                CommandPartProcessResult(
                    expanded_part=maybe_expanded_parts,
                    ban_result=maybe_ban_result,
                )
            )
            continue

        # 이동
        for move_data in calculator.move_list:
            context.move_character_to(move_data.character_id, move_data.to_position)

        remaining_parts_dict[command.user_id].extend(part_data.damage_list)
        remaining_parts_dict[command.user_id].extend(part_data.heal_list)

        # 버프 추가
        for buff_add_event in part_data.buff_add_list:
            if buff_add_event.add_timing == RoundPhaseType.ENEMY_PRE_ACTION:
                context.buff_container.add(buff_add_event)
            elif buff_add_event.add_timing == RoundPhaseType.ENEMY_POST_ACTION:
                remaining_parts_dict[command.user_id].append(buff_add_event)

    print(results_per_part)

    # 적군은 아직 처리하지 않은 parts가 남아 있어도 선언 시점에 코스트 전부 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    return CommandProcessResult(original_command=command, part_results=results_per_part)


# Post-action에서는 에너미가 살아있을 경우 공격 대미지만 처리.
# 공격 대상에게 디버프를 부여하는 등 "공격의 부가 효과"로 설정된 버프는 POST 타이밍으로 이곳에서 처리한다.
def try_process_enemy_command_on_post_action(
    context: BattlefieldContext,
    user_id: CharacterId,
    remaining_data: list[DamageData | HealData | BuffAddData],
) -> Optional[CommandPartProcessResult]:
    # 적이 사망했다면 패스
    if user_id not in context.characters.keys():
        return None

    damage_list = [data for data in remaining_data if isinstance(data, DamageData)]
    heal_list = [data for data in remaining_data if isinstance(data, HealData)]
    buff_add_list = [data for data in remaining_data if isinstance(data, BuffAddData)]
    command_part = CommandPartData(
        None,
        move_list=[],
        damage_list=damage_list,
        heal_list=heal_list,
        buff_add_list=buff_add_list,
    )
    calculator = CommandPartCalculator(command_part, context)

    # 행동 가능 여부 체크
    ban_results = _get_ban_results(calculator, context, user_id)

    maybe_ban_result: Optional[BanResult] = None
    for ban_result in ban_results:
        if ban_result.is_banned:
            maybe_ban_result = ban_result
            break
    if maybe_ban_result:
        return CommandPartProcessResult(
            expanded_part=command_part,
            ban_result=maybe_ban_result,
        )

    _process_damage(calculator, context)
    _process_heal(calculator, context)

    # 버프 추가
    for buff_add_event in command_part.buff_add_list:
        if buff_add_event.add_timing == RoundPhaseType.ENEMY_POST_ACTION:
            context.buff_container.add(buff_add_event)

    return CommandPartProcessResult(command_part, ban_result=None)


def try_expansion_if_valid(
    context: BattlefieldContext, command: CharacterCommand
) -> Optional[tuple[list[CommandPartData], int]]:
    """
    커맨드 실행 전 사전 검증. 문제가 있으면 CommandValidationError를 raise한다.
    검증 항목:
      1. 커맨드 사용자가 전장에 존재하는지
      2. 코스트가 충분한지
      3. 공격/스킬 대상이 전장에 존재하는지
      4. 이동 목적지에 자리가 남아있는지
      5. 공격 대상이 사거리 내인지
    """

    # 1. 사용자 존재 확인
    if command.user_id not in context.characters:
        raise CommandValidationError(error_target_does_not_exist(command.user_id))

    user = context.characters[command.user_id]
    user_pos = context.find_character_position(command.user_id)
    attack_range = user.status[CombatStatType.RANGE]

    # 2. 코스트 확인
    # 커맨드 전체의 코스트를 한꺼번에 산출한다. (되는 데까지 처리해주지 않고 전체 코스트가 부족하다면 아예 미처리)
    needed_cost = get_total_cost(command.parts, command.user_id, context)
    if user.status.remaining_cost < needed_cost:
        raise CommandValidationError(
            error_no_remaining_cost(needed_cost, user.status.remaining_cost)
        )

    expanded_command_data_list = expand_character_command(command, context)
    for command_data in expanded_command_data_list:
        # 3. 대미지/힐 대상 존재 및 사거리 확인
        for damage_data in command_data.damage_list:
            target_id = damage_data.target_id
            if target_id not in context.characters:
                raise CommandValidationError(error_target_does_not_exist(target_id))

            target_pos = context.find_character_position(target_id)
            if not is_reachable(user_pos, target_pos, attack_range):
                raise CommandValidationError(error_attack_position_too_far(target_pos))

        for heal_data in command_data.heal_list:
            target_id = heal_data.target_id
            if target_id not in context.characters:
                raise CommandValidationError(error_target_does_not_exist(target_id))

        # 4. 이동 목적지 검증
        for move_data in command_data.move_list:
            to_pos = move_data.to_position
            if context.try_find_empty_slot(user.faction, to_pos) is None:
                raise CommandValidationError(error_too_many_characters(to_pos))

    return expanded_command_data_list, needed_cost


def _apply_buff_events(
    calculator: CommandPartCalculator,
    context: BattlefieldContext,
    char_id,
    timing: BuffApplyTiming,
    attacker_or_target=None,
):
    buffs = context.buff_container.get_buffs_by(char_id, timing)
    events = [buff.create_event() for buff in buffs]
    events.sort(key=lambda e: e.priority.value)
    for event in events:
        if event.is_applied(context, char_id, attacker_or_target):
            event.apply(char_id, attacker_or_target, context, calculator)


def _get_ban_results(
    calculator: CommandPartCalculator, context: BattlefieldContext, user_id: CharacterId
) -> list[BanResult]:
    _apply_buff_events(calculator, context, user_id, BuffApplyTiming.ON_ACTION)
    return [
        BanResult(event.is_applied(context, user_id, None), event)
        for event in calculator.ban_event_list
        if isinstance(event, BanActionEvent)
    ]


def _process_damage(
    calculator: CommandPartCalculator, context: BattlefieldContext
) -> None:
    for damage_calc in list(calculator.damage_data_list):
        _apply_buff_events(
            calculator,
            context,
            damage_calc.base.attacker_id,
            BuffApplyTiming.ON_ATTACK,
            damage_calc.base.target_id,
        )
        _apply_buff_events(
            calculator,
            context,
            damage_calc.base.target_id,
            BuffApplyTiming.ON_HIT,
            damage_calc.base.attacker_id,
        )
    for damage_calc in calculator.damage_data_list:
        attacker = context.characters[damage_calc.base.attacker_id]
        target = context.characters[damage_calc.base.target_id]

        if attacker.status.is_magic_attacker:
            damage_calc.modifiers.append(target.status.m_res)
        damage_calc.modifiers.append(get_bonus_damage(target.element, attacker.element))

        context.apply_damage(
            damage_calc.base.attacker_id,
            damage_calc.base.target_id,
            ValueWithModifiers(damage_calc.base.value, damage_calc.modifiers),
            calculator,
        )


def _process_heal(
    calculator: CommandPartCalculator, context: BattlefieldContext
) -> None:
    for heal_calc in list(calculator.heal_data_list):
        _apply_buff_events(
            calculator,
            context,
            heal_calc.base.healer_id,
            BuffApplyTiming.ON_GIVE_HEAL,
            heal_calc.base.target_id,
        )
        _apply_buff_events(
            calculator,
            context,
            heal_calc.base.target_id,
            BuffApplyTiming.ON_RECEIVE_HEAL,
            heal_calc.base.healer_id,
        )
    for heal_calc in calculator.heal_data_list:
        context.apply_heal(
            heal_calc.base.healer_id,
            heal_calc.base.target_id,
            ValueWithModifiers(heal_calc.base.value, heal_calc.modifiers),
            calculator,
        )
