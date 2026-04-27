from typing import TYPE_CHECKING

from battle.admin_utils import AdminCommandData, ChangePhaseCommandData
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import (
    BanResult,
    CommandCalculator,
    CommandData,
    CommandProcessResult,
)
from battle.exceptions import (
    CommandValidationError,
    error_attack_position_too_far,
    error_move_position_too_far,
    error_no_remaining_cost,
    error_target_does_not_exist,
    error_too_many_characters,
)
from battle.objects.buff.buffs.buff_ban_action import BanActionEvent
from battle.objects.define import ActionType, BuffApplyTiming, CombatStatType
from battle.objects.extensions import to_cost
from battle.objects.models import ValueWithModifiers
from utils.battle_helpers import is_reachable

if TYPE_CHECKING:
    from battle.core.round_manager import RoundManager


def process_admin_command(
    round_manager: "RoundManager", command: AdminCommandData
) -> None:
    if isinstance(command, ChangePhaseCommandData):
        round_manager.to_phase(command.target_phase)


def is_valid(context: BattlefieldContext, command: CommandData) -> None:
    """
    커맨드 실행 전 사전 검증. 문제가 있으면 CommandValidationError를 raise한다.
    검증 항목:
      1. 커맨드 사용자가 전장에 존재하는지
      2. 코스트가 충분한지
      3. 공격/스킬 대상이 전장에 존재하는지
      4. 이동 목적지가 사거리 내인지, 자리가 남아있는지
      5. 공격 대상이 사거리 내인지
    """
    user_id = command.command.user

    # 1. 사용자 존재 확인
    if user_id not in context.characters:
        raise CommandValidationError(error_target_does_not_exist(user_id))

    user = context.characters[user_id]
    user_pos = context.find_character_position(user_id)
    attack_range = user.status[CombatStatType.RANGE]

    # 2. 코스트 확인
    # ActionCommand인 경우에만 코스트 차감이 필요하다.
    # command.command의 타입에 따라 필요한 코스트를 산출한다.
    from battle.core.commands.models import ActionCommand, ItemCommand

    if isinstance(command.command, (ActionCommand, ItemCommand)):
        needed_cost = to_cost(command.command.type_)
        if user.status.remaining_cost < needed_cost:
            raise CommandValidationError(
                error_no_remaining_cost(needed_cost, user.status.remaining_cost)
            )

    # 3. 대미지/힐 대상 존재 및 사거리 확인
    for damage_data in command.damage_list:
        target_id = damage_data.target_id
        if target_id not in context.characters:
            raise CommandValidationError(error_target_does_not_exist(target_id))

        target_pos = context.find_character_position(target_id)
        if not is_reachable(user_pos, target_pos, attack_range):
            raise CommandValidationError(error_attack_position_too_far(target_pos))

    for heal_data in command.heal_list:
        target_id = heal_data.target_id
        if target_id not in context.characters:
            raise CommandValidationError(error_target_does_not_exist(target_id))

    # 4. 이동 목적지 검증
    for move_data in command.move_list:
        to_pos = move_data.to_position
        if not is_reachable(user_pos, to_pos, attack_range):
            raise CommandValidationError(error_move_position_too_far(to_pos))
        if context.try_find_empty_slot(user.faction, to_pos) is None:
            raise CommandValidationError(error_too_many_characters(to_pos))


def _apply_buff_events(
    calculator: CommandCalculator,
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


def process_ally_command(
    context: BattlefieldContext, command: CommandData
) -> CommandProcessResult:
    # 사전 검증 - 문제 있으면 여기서 raise
    is_valid(context, command)

    calculator = CommandCalculator(command, context)

    # 1. 행동 가능 여부 체크
    _apply_buff_events(
        calculator, context, command.command.user, BuffApplyTiming.ON_ACTION
    )
    ban_results = [
        BanResult(event.is_applied(context, command.command.user, None), event)
        for event in calculator.ban_event_list
        if isinstance(event, BanActionEvent)
    ]
    for ban_result in ban_results:
        if ban_result.is_banned:
            return CommandProcessResult(command_data=command, ban_result=ban_result)

    # 2. 이동
    for move_data in calculator.command_data.move_list:
        context.move_character_to(move_data.character_id, move_data.to_position)

    # 3. 대미지
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
        context.apply_damage(
            damage_calc.base.attacker_id,
            damage_calc.base.target_id,
            ValueWithModifiers(damage_calc.base.value, damage_calc.modifiers),
        )

    # 4. 힐
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
        )

    # 5. 버프 추가
    for buff_add_event in command.buff_add_list:
        context.buff_container.add(buff_add_event)

    # 코스트 차감 - 검증 통과 후 실제 처리 시점에 차감
    from battle.core.commands.models import ActionCommand, ItemCommand

    if isinstance(command.command, (ActionCommand, ItemCommand)):
        user = context.characters[command.command.user]
        user.status.remaining_cost -= to_cost(command.command.type_)

    return CommandProcessResult(command_data=command)


def process_enemy_command(context: BattlefieldContext, command: CommandData) -> None:
    pass
