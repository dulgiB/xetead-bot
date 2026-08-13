from dataclasses import replace
from typing import TYPE_CHECKING

from utils.battle_helpers import is_reachable

from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_calculator import CommandPartCalculator, build_log_entries
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
    error_item_does_not_exist,
    error_item_has_no_effect,
    error_item_not_usable_here,
    error_no_item_in_inventory,
    error_no_remaining_cost,
    error_skill_not_registered,
    error_target_does_not_exist,
    error_target_is_companion,
    error_too_many_characters,
    error_too_many_targets,
)
from battle.objects.define import ActionType, BattlefieldColumnIndex, CombatStatType
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
        if data is None:
            continue
        for move_data in data.move_list:
            round_manager._context.move_character_to(
                move_data.character_id, move_data.to_position
            )
        for damage_data in data.damage_list:
            round_manager._context.apply_damage(
                damage_data.attacker_id,
                damage_data.target_id,
                ValueWithModifiers(damage_data.value, [], []),
                None,
                i,
            )
        for heal_data in data.heal_list:
            round_manager._context.apply_heal(
                heal_data.healer_id,
                heal_data.target_id,
                ValueWithModifiers(heal_data.value, [], []),
                None,
                i,
            )

        for buff_add_event in data.buff_add_list:
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
        assert (
            isinstance(part_data, CommandPartData)
            and part_data.original_part is not None
        )
        calculator = CommandPartCalculator(part_data, context)
        calculator.process(RoundPhaseType.ALLY_ACTION)
        results_per_part.append(
            CommandPartProcessResult(
                expanded_part=part_data,
                log_entries=build_log_entries(calculator),
            )
        )

    # 코스트 차감 - 검증 통과 후 실제 처리 시점에 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    # 아이템 소비 - 검증·처리 완료 후 보유 개수 차감 (시트에도 즉시 반영)
    for part in command.parts:
        if part.type_ == ActionType.USE_ITEM and part.item_id is not None:
            context.inventory.consume(command.user_id.name, part.item_id)

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

    results_per_part: list[CommandPartProcessResult] = []
    for part_data in maybe_expanded_parts:
        assert (
            isinstance(part_data, CommandPartData)
            and part_data.original_part is not None
        )
        calculator = CommandPartCalculator(part_data, context)
        calculator.process(RoundPhaseType.ENEMY_PRE_ACTION)
        results_per_part.append(
            CommandPartProcessResult(
                expanded_part=part_data,
                log_entries=build_log_entries(calculator),
            )
        )

    # 원본 커맨드를 저장 — POST 페이즈에서 도발 등 버프를 반영해 재전개
    remaining_commands_dict.setdefault(command.user_id, []).append(command)

    # 적군은 아직 처리하지 않은 parts가 남아 있어도 선언 시점에 코스트 전부 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    return CommandProcessResult(original_command=command, part_results=results_per_part)


# Post-action에서는 에너미가 살아있을 경우 저장된 원본 커맨드를 재전개해 대미지/힐/POST 버프를 처리.
# 재전개 시점에 도발 등 현재 버프 상태가 반영되므로, PRE 선언 이후 걸린 도발도 정상 적용된다.
def try_process_enemy_command_on_post_action(
    context: BattlefieldContext,
    user_id: CharacterId,
    remaining_commands: list[CharacterCommand],
) -> list[CommandPartProcessResult]:
    # 적이 사망했다면 패스. 체력 0 이하 캐릭터의 실제 제거는 라운드 종료
    # 시점(_remove_eliminated_characters)에 한 번에 처리되므로, ALLY_ACTION
    # 중 체력이 0이 된 적은 이 시점에도 여전히 context.characters에 남아
    # 있다 — 필드 제거 여부만으로는 사망을 판정할 수 없고 체력을 직접
    # 확인해야 한다. 그렇지 않으면 이미 죽은 적의 PRE 선언 공격이 POST에
    # 그대로 적용되어 버린다.
    if user_id not in context.characters:
        return []
    if context.characters[user_id].status.curr_hp <= 0:
        return []

    results: list[CommandPartProcessResult] = []
    for command in remaining_commands:
        expanded_parts = expand_character_command(command, context)
        for part_data in expanded_parts:
            post_part = part_data.create_new_except_move()
            calculator = CommandPartCalculator(post_part, context)
            calculator.process(RoundPhaseType.ENEMY_POST_ACTION)
            results.append(
                CommandPartProcessResult(
                    expanded_part=post_part,
                    log_entries=build_log_entries(calculator),
                )
            )
    return results


def try_expansion_if_valid(
    context: BattlefieldContext, command: CharacterCommand
) -> tuple[list[CommandPartData], int]:
    """
    커맨드 실행 전 사전 검증. 문제가 있으면 CommandValidationError를 raise한다.
    (None을 반환하는 경우는 없다 — 검증 실패는 항상 예외로 알린다.)
    검증 항목:
      1. 커맨드 사용자가 전장에 존재하는지
      2. 코스트가 충분한지
      3. 이동 목적지에 자리가 남아있는지 (이동 후 user_pos 갱신)
      4. 공격/스킬 대상이 전장에 존재하고 사거리 내인지 (갱신된 위치 기준)
      5. 커맨드가 동료(소환수)를 명시적으로 대상 지정하지 않았는지 — 동료는
         owner에게 종속된 실드 개념이라 직접 대상으로 선언할 수 없다. 코스트 3
         스킬처럼 스킬 효과가 내부적으로 동료를 대상으로 계산하는 것은
         플레이어의 "선언"이 아니므로 이 검증 대상이 아니다(그런 내부 target_id는
         원본 커맨드의 targets에 나타나지 않는다).
    """

    if command.user_id not in context.characters:
        raise CommandValidationError(error_target_does_not_exist(command.user_id))

    user = context.characters[command.user_id]
    user_pos = context.find_character_position(command.user_id)
    attack_range = user.status[CombatStatType.RANGE]

    # 1.5. 캐릭터/스킬/아이템 이름 공백 무시 매칭 — 사용자가 입력한 공백이
    # 등록된 표기와 다르더라도(예: "변칙공격" vs "변칙 공격") 등록된 표기로
    # 치환해 이후 검증·전개가 정확한 값으로 이루어지도록 한다. 이 시점에
    # 플레이어가 직접 타이핑한 대상만 동료 여부를 검사한다.
    command.parts[:] = [
        replace(
            part,
            skill_id=(
                context.resolve_skill_id(command.user_id, part.skill_id)
                if part.type_ == ActionType.SKILL and part.skill_id is not None
                else part.skill_id
            ),
            item_id=(
                context.resolve_item_id(part.item_id)
                if part.type_ == ActionType.USE_ITEM and part.item_id is not None
                else part.item_id
            ),
            targets=[
                _resolve_and_reject_companion_target(context, t) for t in part.targets
            ],
        )
        for part in command.parts
    ]

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

        elif part.type_ == ActionType.USE_ITEM and part.item_id is not None:
            # 대련 등 아이템을 사용할 수 없는 전장인지 확인
            if not context.allow_item_usage:
                raise CommandValidationError(error_item_not_usable_here())
            if not context.has_item(part.item_id):
                raise CommandValidationError(error_item_does_not_exist(part.item_id))
            if context.inventory.get_count(command.user_id.name, part.item_id) <= 0:
                raise CommandValidationError(error_no_item_in_inventory(part.item_id))
            if context.get_item_data_by_id(part.item_id).effect is None:
                raise CommandValidationError(error_item_has_no_effect(part.item_id))

    # 커맨드 전체의 코스트를 한꺼번에 산출한다 — 되는 데까지 처리해주지 않고
    # 전체 코스트가 부족하면 아예 미처리한다.
    needed_cost = get_total_cost(command.parts, command.user_id, context)
    if user.status.remaining_cost < needed_cost:
        raise CommandValidationError(
            error_no_remaining_cost(needed_cost, user.status.remaining_cost)
        )

    expanded_command_data_list = expand_character_command(command, context)
    for command_data in expanded_command_data_list:
        # 아이템은 고유 사거리를 사용하고, 그 외(공격/스킬)는 캐릭터의 사거리 스탯을 사용한다.
        original_part = command_data.original_part
        if (
            original_part is not None
            and original_part.type_ == ActionType.USE_ITEM
            and original_part.item_id is not None
        ):
            effective_range = context.get_item_data_by_id(
                original_part.item_id
            ).attack_range
        else:
            effective_range = attack_range

        for sub_data in command_data.data_per_effect:
            if sub_data is None:
                continue

            # 이동 목적지는 damage 검증보다 먼저 수행해 user_pos를 갱신한다.
            # 슬롯 점유 여부는 실제로 이동하는 캐릭터(move_data.character_id)의
            # 진영 기준으로 확인해야 한다 — 시전자의 진영으로 확인하면, 다른
            # 진영의 캐릭터를 이동시키는 스킬(끌어당기기/밀어내기, 대상을
            # 지정한 열로 이동시키는 스킬 등)에서 엉뚱한 진영의 열 점유 상태를
            # 검사하게 된다.
            for move_data in sub_data.move_list:
                to_pos = move_data.to_position
                mover_id = move_data.character_id
                if mover_id not in context.characters:
                    raise CommandValidationError(error_target_does_not_exist(mover_id))
                mover_faction = context.characters[mover_id].faction
                if context.try_find_empty_slot(mover_faction, to_pos) is None:
                    raise CommandValidationError(error_too_many_characters(to_pos))
                if mover_id == command.user_id:
                    user_pos = to_pos

            for damage_data in sub_data.damage_list:
                target_id = damage_data.target_id
                if target_id not in context.characters:
                    raise CommandValidationError(error_target_does_not_exist(target_id))

                target_pos = context.find_character_position(target_id)
                if not is_reachable(user_pos, target_pos, effective_range):
                    raise CommandValidationError(
                        error_attack_position_too_far(target_pos)
                    )

            for heal_data in sub_data.heal_list:
                target_id = heal_data.target_id
                if target_id not in context.characters:
                    raise CommandValidationError(error_target_does_not_exist(target_id))

    return expanded_command_data_list, needed_cost


def _resolve_and_reject_companion_target(
    context: BattlefieldContext, target: "CharacterId | BattlefieldColumnIndex"
) -> "CharacterId | BattlefieldColumnIndex":
    if not isinstance(target, CharacterId):
        return target
    resolved = context.resolve_character_id(target)
    if resolved in context.companion_owners:
        raise CommandValidationError(error_target_is_companion(resolved))
    return resolved
