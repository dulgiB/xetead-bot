from typing import TYPE_CHECKING, Optional

from utils.battle_helpers import is_reachable

from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_calculator import CommandPartCalculator
from battle.core.command_expanders import expand_character_command
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import (
    CharacterCommand,
    CommandPartData,
    CommandPartProcessResult,
    CommandProcessResult,
)
from battle.exceptions import (
    CommandValidationError,
    error_attack_position_too_far,
    error_no_remaining_cost,
    error_skill_not_registered,
    error_target_does_not_exist,
    error_too_many_characters,
    error_too_many_targets,
)
from battle.objects.define import ActionType, CombatStatType
from battle.objects.extensions import get_total_cost
from battle.objects.models import CharacterId, ValueWithModifiers

if TYPE_CHECKING:
    from battle.core.round_manager import RoundManager


def process_admin_command(
    round_manager: "RoundManager", expanded_command: CommandPartData
) -> None:
    if expanded_command.admin_target_phase:
        round_manager.to_phase(expanded_command.admin_target_phase)
        return

    for i in range(len(expanded_command.data_per_effect)):
        data = expanded_command.data_per_effect[i]
        for move_data in data.move_list:
            round_manager._context.move_character_to(
                move_data.character_id, move_data.to_position
            )
        for damage_data in data.damage_list:
            round_manager._context.apply_damage(
                damage_data.attacker_id,
                damage_data.target_id,
                ValueWithModifiers(damage_data.value, []),
                None,
                i,
            )
        for heal_data in data.heal_list:
            round_manager._context.apply_heal(
                heal_data.healer_id,
                heal_data.target_id,
                ValueWithModifiers(heal_data.value, []),
                None,
                i,
            )

        for buff_add_event in data.buff_add_list:
            round_manager._context.buff_container.add(buff_add_event)

        for buff_to_remove in data.admin_buff_remove_list:
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
        assert (
            isinstance(part_data, CommandPartData)
            and part_data.original_part is not None
        )
        calculator = CommandPartCalculator(part_data, context)
        calculator.process(RoundPhaseType.ALLY_ACTION)
        results_per_part.append(CommandPartProcessResult(expanded_part=part_data))

    # 코스트 차감 - 검증 통과 후 실제 처리 시점에 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    return CommandProcessResult(original_command=command, part_results=results_per_part)


# Pre-action에서는 이동과 PRE 타이밍 버프 부여를 처리. 원본 커맨드는 POST에서 재전개하기 위해 저장.
def process_enemy_command_on_pre_action(
    context: BattlefieldContext,
    command: CharacterCommand,
    remaining_commands_dict: dict[CharacterId, list[CharacterCommand]],
) -> CommandProcessResult:
    # 사전 검증 - 문제 있으면 여기서 raise
    maybe_expanded_parts, needed_cost = try_expansion_if_valid(context, command)
    if not maybe_expanded_parts:
        return CommandProcessResult(original_command=command, part_results=[])

    for part_data in maybe_expanded_parts:
        assert (
            isinstance(part_data, CommandPartData)
            and part_data.original_part is not None
        )
        calculator = CommandPartCalculator(part_data, context)
        calculator.process(RoundPhaseType.ENEMY_PRE_ACTION)

    # 원본 커맨드를 저장 — POST 페이즈에서 도발 등 버프를 반영해 재전개
    remaining_commands_dict.setdefault(command.user_id, []).append(command)

    # 적군은 아직 처리하지 않은 parts가 남아 있어도 선언 시점에 코스트 전부 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    return CommandProcessResult(original_command=command, part_results=[])


# Post-action에서는 에너미가 살아있을 경우 저장된 원본 커맨드를 재전개해 대미지/힐/POST 버프를 처리.
# 재전개 시점에 도발 등 현재 버프 상태가 반영되므로, PRE 선언 이후 걸린 도발도 정상 적용된다.
def try_process_enemy_command_on_post_action(
    context: BattlefieldContext,
    user_id: CharacterId,
    remaining_commands: list[CharacterCommand],
) -> list[CommandPartProcessResult]:
    # 적이 사망했다면 패스
    if user_id not in context.characters:
        return []

    results: list[CommandPartProcessResult] = []
    for command in remaining_commands:
        expanded_parts = expand_character_command(command, context)
        for part_data in expanded_parts:
            # 이동은 PRE에서 이미 처리했으므로 제외
            post_part = CommandPartData(
                part_data.original_part,
                data_per_effect=part_data.data_per_effect,
            )
            calculator = CommandPartCalculator(post_part, context)
            calculator.process(RoundPhaseType.ENEMY_POST_ACTION)
            results.append(CommandPartProcessResult(post_part))
    return results


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

    # 2. 스킬 존재 여부 및 대상 수 확인
    for part in command.parts:
        if part.type_ == ActionType.SKILL and part.skill_id is not None:
            skill = next((s for s in user.skills if s.data.id == part.skill_id), None)
            if skill is None:
                raise CommandValidationError(error_skill_not_registered(part.skill_id))
            if len(part.targets) > skill.data.target_count:
                raise CommandValidationError(
                    error_too_many_targets(
                        part.skill_id, skill.data.target_count, len(part.targets)
                    )
                )

    # 3. 코스트 확인
    # 커맨드 전체의 코스트를 한꺼번에 산출한다. (되는 데까지 처리해주지 않고 전체 코스트가 부족하다면 아예 미처리)
    needed_cost = get_total_cost(command.parts, command.user_id, context)
    if user.status.remaining_cost < needed_cost:
        raise CommandValidationError(
            error_no_remaining_cost(needed_cost, user.status.remaining_cost)
        )

    expanded_command_data_list = expand_character_command(command, context)
    for command_data in expanded_command_data_list:
        for sub_data in command_data.data_per_effect:
            if sub_data is None:
                continue

            # 4. 대미지/힐 대상 존재 및 사거리 확인
            for damage_data in sub_data.damage_list:
                target_id = damage_data.target_id
                if target_id not in context.characters:
                    raise CommandValidationError(error_target_does_not_exist(target_id))

                target_pos = context.find_character_position(target_id)
                if not is_reachable(user_pos, target_pos, attack_range):
                    raise CommandValidationError(
                        error_attack_position_too_far(target_pos)
                    )

            for heal_data in sub_data.heal_list:
                target_id = heal_data.target_id
                if target_id not in context.characters:
                    raise CommandValidationError(error_target_does_not_exist(target_id))

            # 5. 이동 목적지 검증
            for move_data in sub_data.move_list:
                to_pos = move_data.to_position
                if context.try_find_empty_slot(user.faction, to_pos) is None:
                    raise CommandValidationError(error_too_many_characters(to_pos))

    return expanded_command_data_list, needed_cost
