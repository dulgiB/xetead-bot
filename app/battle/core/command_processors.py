from typing import TYPE_CHECKING, Optional

from battle.admin_utils import ChangePhaseCommand
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_expanders import expand_character_command
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
from battle.objects.buff.buffs.buff_ban_action import BanActionEvent
from battle.objects.define import BuffApplyTiming, CombatStatType
from battle.objects.extensions import get_total_cost
from battle.objects.models import ValueWithModifiers
from utils.battle_helpers import is_reachable

if TYPE_CHECKING:
    from battle.core.round_manager import RoundManager


def process_admin_command(
    round_manager: "RoundManager", expanded_command: CommandPartData
) -> None:
    if expanded_command.admin_target_phase:
        round_manager.to_phase(expanded_command.admin_target_phase)


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

        # 1. 행동 가능 여부 체크
        _apply_buff_events(
            calculator, context, command.user_id, BuffApplyTiming.ON_ACTION
        )
        ban_results = [
            BanResult(event.is_applied(context, command.user_id, None), event)
            for event in calculator.ban_event_list
            if isinstance(event, BanActionEvent)
        ]

        maybe_ban_result: Optional[BanResult] = None
        for ban_result in ban_results:
            if ban_result.is_banned:
                maybe_ban_result = ban_result
                break
        if maybe_ban_result:
            results_per_part.append(
                CommandPartProcessResult(
                    original_part=part_data.original_part, ban_result=maybe_ban_result
                )
            )
            continue

        # 2. 이동
        for move_data in calculator.data.move_list:
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
        for buff_add_event in part_data.buff_add_list:
            context.buff_container.add(buff_add_event)

    # 코스트 차감 - 검증 통과 후 실제 처리 시점에 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    return CommandProcessResult(original_command=command, part_results=results_per_part)


# TODO
def process_enemy_command(
    context: BattlefieldContext, command: CharacterCommand
) -> None:
    pass


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

    expanded_command_data_list = expand_character_command(command)
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
