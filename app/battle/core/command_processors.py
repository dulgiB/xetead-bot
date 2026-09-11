from dataclasses import replace
from typing import TYPE_CHECKING, Optional

from utils.battle_helpers import is_reachable

from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_calculator import CommandPartCalculator, build_log_entries
from battle.core.command_expanders import expand_character_command
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import (
    BattleLogEntry,
    BattleLogEntryKind,
    CharacterCommand,
    CommandPart,
    CommandPartData,
    CommandPartProcessResult,
    CommandProcessResult,
)
from battle.core.taunt_redirect import assign_taunt_redirects
from battle.exceptions import (
    CommandValidationError,
    error_attack_position_too_far,
    error_character_is_defeated,
    error_fate_already_used,
    error_fate_not_available_here,
    error_fate_not_enough_hp,
    error_fate_only_once_per_command,
    error_fate_requires_revival,
    error_fate_skill_without_damage,
    error_fate_unsupported_command,
    error_item_does_not_exist,
    error_item_has_no_effect,
    error_item_not_usable_here,
    error_item_not_usable_in_battle,
    error_no_item_in_inventory,
    error_no_remaining_cost,
    error_skill_not_registered,
    error_target_does_not_exist,
    error_target_is_companion,
    error_too_many_characters,
    error_too_many_targets,
)
from battle.objects.define import (
    FATE_INTERVENTION_HP_COST,
    FATE_INTERVENTION_REQUIRED_REVIVAL_COUNT,
    ActionType,
    BattlefieldColumnIndex,
    CombatStatType,
    FateBoostMode,
    ItemType,
)
from battle.objects.extensions import get_total_cost
from battle.objects.models import CharacterId, ValueWithModifiers

if TYPE_CHECKING:
    from battle.core.round_manager import RoundManager
    from battle.objects.character.combat_character import CombatCharacter
    from battle.objects.skill.models import SkillData


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
    maybe_expanded_parts, needed_cost = try_expansion_if_valid(context, command)
    if not maybe_expanded_parts:
        return CommandProcessResult(original_command=command, part_results=[])

    for part_data in maybe_expanded_parts:
        assert (
            isinstance(part_data, CommandPartData)
            and part_data.original_part is not None
        )

    calculators = [
        CommandPartCalculator(part_data, context) for part_data in maybe_expanded_parts
    ]
    assign_taunt_redirects(
        context, command.user_id, calculators, RoundPhaseType.ALLY_ACTION
    )

    results_per_part: list[CommandPartProcessResult] = []
    for part_data, calculator in zip(maybe_expanded_parts, calculators):
        calculator.process(RoundPhaseType.ALLY_ACTION)
        results_per_part.append(
            CommandPartProcessResult(
                expanded_part=part_data,
                log_entries=build_log_entries(calculator),
                redirect_map=calculator.redirect_map,
            )
        )

    # 코스트·체력·아이템은 검증과 실제 처리를 모두 통과한 뒤에만 소모한다.
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost
    _apply_fate_intervention_cost(user, command, results_per_part)
    for part in command.parts:
        if part.type_ == ActionType.USE_ITEM and part.item_id is not None:
            context.inventory.consume(command.user_id.name, part.item_id)

    return CommandProcessResult(original_command=command, part_results=results_per_part)


def process_enemy_command_on_pre_action(
    context: BattlefieldContext,
    command: CharacterCommand,
    remaining_commands_dict: dict[CharacterId, list[CharacterCommand]],
) -> CommandProcessResult:
    maybe_expanded_parts, needed_cost = try_expansion_if_valid(context, command)
    if not maybe_expanded_parts:
        return CommandProcessResult(original_command=command, part_results=[])

    for part_data in maybe_expanded_parts:
        assert (
            isinstance(part_data, CommandPartData)
            and part_data.original_part is not None
        )

    calculators = [
        CommandPartCalculator(part_data, context) for part_data in maybe_expanded_parts
    ]
    assign_taunt_redirects(
        context, command.user_id, calculators, RoundPhaseType.ENEMY_PRE_ACTION
    )

    results_per_part: list[CommandPartProcessResult] = []
    for part_data, calculator in zip(maybe_expanded_parts, calculators):
        calculator.process(RoundPhaseType.ENEMY_PRE_ACTION)
        results_per_part.append(
            CommandPartProcessResult(
                expanded_part=part_data,
                log_entries=build_log_entries(calculator),
                redirect_map=calculator.redirect_map,
            )
        )

    # 원본 커맨드를 저장 — POST 페이즈에서 도발 등 버프를 반영해 재전개
    remaining_commands_dict.setdefault(command.user_id, []).append(command)

    # 적군은 아직 처리하지 않은 parts가 남아 있어도 선언 시점에 코스트 전부 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    # 운명간섭 대가도 코스트와 같이 선언 시점에 소모한다 — POST에서 소모하면
    # 재전개마다 중복 소모되거나 아예 누락된다.
    _apply_fate_intervention_cost(user, command, results_per_part)

    return CommandProcessResult(original_command=command, part_results=results_per_part)


# 재전개 시점의 버프 상태가 반영되므로, PRE 선언 이후 걸린 도발도 정상 적용된다.
def try_process_enemy_command_on_post_action(
    context: BattlefieldContext,
    user_id: CharacterId,
    remaining_commands: list[CharacterCommand],
) -> list[CommandPartProcessResult]:
    # 실제 제거는 라운드 종료 시점에 한 번에 일어나므로, ALLY_ACTION 중
    # 체력이 0이 된 적은 아직 characters에 남아 있다 — 필드 잔류 여부가
    # 아니라 체력을 직접 봐야 죽은 적의 PRE 선언이 POST에 적용되지 않는다.
    if user_id not in context.characters:
        return []
    if context.characters[user_id].status.curr_hp <= 0:
        return []

    post_parts: list[CommandPartData] = []
    for command in remaining_commands:
        expanded_parts = expand_character_command(command, context)
        for part_data in expanded_parts:
            post_parts.append(part_data.create_new_except_move())

    calculators = [
        CommandPartCalculator(post_part, context) for post_part in post_parts
    ]
    assign_taunt_redirects(
        context, user_id, calculators, RoundPhaseType.ENEMY_POST_ACTION
    )

    results: list[CommandPartProcessResult] = []
    for post_part, calculator in zip(post_parts, calculators):
        calculator.process(RoundPhaseType.ENEMY_POST_ACTION)
        results.append(
            CommandPartProcessResult(
                expanded_part=post_part,
                log_entries=build_log_entries(calculator),
                redirect_map=calculator.redirect_map,
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
      2. 커맨드 사용자의 체력이 0보다 큰지 (행동 주체 기준. 진영 무관)
      3. 코스트가 충분한지
      4. 이동 목적지에 자리가 남아있는지 (이동 후 user_pos 갱신)
      5. 공격/스킬 대상이 전장에 존재하고 사거리 내인지 (갱신된 위치 기준)
      6. 커맨드가 동료(소환수)를 명시적으로 대상 지정하지 않았는지 — 동료는
         owner에게 종속된 실드 개념이라 직접 대상으로 선언할 수 없다. 코스트 3
         스킬처럼 스킬 효과가 내부적으로 동료를 대상으로 계산하는 것은
         플레이어의 "선언"이 아니므로 이 검증 대상이 아니다(그런 내부 target_id는
         원본 커맨드의 targets에 나타나지 않는다).
      7. 운명간섭("+")을 붙였다면 그 사용 조건을 만족하는지
    """

    if command.user_id not in context.characters:
        raise CommandValidationError(error_target_does_not_exist(command.user_id))

    user = context.characters[command.user_id]

    # 아군은 체력이 0이어도 부활 여지 때문에 필드에 남으므로, 행동 주체만
    # 여기서 막는다 — 대상으로 지정되는 것은 여전히 허용된다.
    if user.status.curr_hp <= 0:
        raise CommandValidationError(error_character_is_defeated())

    user_pos = context.find_character_position(command.user_id)
    attack_range = user.status[CombatStatType.RANGE]

    # 입력한 공백이 등록된 표기와 달라도("스킬_1" vs "스킬 _1") 등록된 표기로
    # 치환해, 이후 검증·전개가 정확한 값을 보게 한다. 동료 여부 검사는 플레이어가
    # 직접 타이핑한 대상에만 걸어야 하므로 이 시점이어야 한다.
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

    fate_part = _validate_fate_boost(context, user, command)

    for part in command.parts:
        if part.type_ == ActionType.SKILL and part.skill_id is not None:
            skill = next((s for s in user.skills if s.data.id == part.skill_id), None)
            if skill is None:
                raise CommandValidationError(error_skill_not_registered(part.skill_id))
            # "대상 추가" 모드는 "+"를 붙였을 때만 대상을 더 지정할 수 있게 한다.
            allowed_target_count = skill.data.target_count + (
                skill.data.fate_boost_value
                if part is fate_part
                and skill.data.fate_mode is FateBoostMode.EXTRA_TARGET
                else 0
            )
            if len(part.targets) > allowed_target_count:
                raise CommandValidationError(
                    error_too_many_targets(
                        part.skill_id, allowed_target_count, len(part.targets)
                    )
                )

        elif part.type_ == ActionType.USE_ITEM and part.item_id is not None:
            if not context.allow_item_usage:
                raise CommandValidationError(error_item_not_usable_here())
            if not context.has_item(part.item_id):
                raise CommandValidationError(error_item_does_not_exist(part.item_id))
            item_type = context.get_item_data_by_id(part.item_id).item_type
            if item_type not in (ItemType.CONSUMABLE, ItemType.BATTLE_CONSUMABLE):
                raise CommandValidationError(error_item_not_usable_in_battle())
            if context.inventory.get_count(command.user_id.name, part.item_id) <= 0:
                raise CommandValidationError(error_no_item_in_inventory(part.item_id))
            if context.get_item_data_by_id(part.item_id).effect is None:
                raise CommandValidationError(error_item_has_no_effect())

    # 되는 데까지 처리해주지 않고, 전체 코스트가 부족하면 아예 미처리한다.
    needed_cost = get_total_cost(command.parts, command.user_id, context)
    if user.status.remaining_cost < needed_cost:
        raise CommandValidationError(
            error_no_remaining_cost(needed_cost, user.status.remaining_cost)
        )

    expanded_command_data_list = expand_character_command(command, context)
    for command_data in expanded_command_data_list:
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

            # 이동은 damage 검증보다 먼저 처리해 user_pos를 갱신한다. 슬롯 점유는
            # 시전자가 아니라 실제로 이동하는 캐릭터의 진영으로 봐야 한다 —
            # 다른 진영을 밀고 당기는 스킬이 엉뚱한 열을 검사하게 된다.
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

    # fate_mode가 없는 스킬은 대미지 스킬에만 운명간섭을 허용한다. 대미지가
    # 실제로 나오는지는 효과 구현체마다 달라 전개해 봐야 알 수 있다.
    if (
        fate_part is not None
        and fate_part.type_ == ActionType.SKILL
        and _fate_skill_data(user, fate_part).fate_mode is None
    ):
        assert fate_part.skill_id is not None
        has_damage = any(
            sub_data.damage_list
            for command_data in expanded_command_data_list
            if command_data.original_part is fate_part
            for sub_data in command_data.data_per_effect
            if sub_data is not None
        )
        if not has_damage:
            raise CommandValidationError(
                error_fate_skill_without_damage(fate_part.skill_id)
            )

    return expanded_command_data_list, needed_cost


def _apply_fate_intervention_cost(
    user: "CombatCharacter",
    command: CharacterCommand,
    results_per_part: list[CommandPartProcessResult],
) -> None:
    """운명간섭을 쓴 커맨드라면 체력을 소모하고 "이번 진행에 사용함"을 표시한다.

    소모량은 대미지 계산 파이프라인을 타지 않는 순수 자원 소비다 — 반사/방어
    버프가 개입하거나 "피격" 반응형 버프가 발동해서는 안 되기 때문이다. 대신
    답글·시트 반영이 기존 경로를 그대로 타도록 대미지 로그 엔트리 형태로
    결과에 얹는다(로그 엔트리의 `result`를 보고 체력을 write-back하는
    `bot/log_sheets.py`의 write_back_changed_hp() 참고).
    """
    if not any(part.fate_boost for part in command.parts):
        return
    if not results_per_part:
        return

    user.status.curr_hp -= FATE_INTERVENTION_HP_COST
    user.fate_used = True
    results_per_part[-1].log_entries.append(
        BattleLogEntry(
            target_name=user.id.name,
            kind=BattleLogEntryKind.DAMAGE,
            result=f"대미지 {FATE_INTERVENTION_HP_COST}",
            value=FATE_INTERVENTION_HP_COST,
            hp_after=user.status.curr_hp,
            max_hp=user.status[CombatStatType.MAX_HP],
            source_labels=("키워드 보정",),
        )
    )


def _fate_skill_data(user: "CombatCharacter", part: CommandPart) -> "SkillData":
    """운명간섭이 붙은 스킬 파트의 SkillData. 스킬 등록 여부는 이 함수를 부르기
    전에 이미 검증돼 있다(error_skill_not_registered)."""
    skill = next((s for s in user.skills if s.data.id == part.skill_id), None)
    assert skill is not None
    return skill.data


def _validate_fate_boost(
    context: BattlefieldContext, user: "CombatCharacter", command: CharacterCommand
) -> Optional[CommandPart]:
    """운명간섭("+") 선언의 사전 조건을 검증하고, 대상 파트를 반환한다.

    "+"가 없으면 None을 반환한다. 대미지 스킬 여부는 커맨드를 전개해 봐야
    알 수 있어 여기서 확인하지 않는다 (try_expansion_if_valid 후반부 참고).
    """
    fate_parts = [part for part in command.parts if part.fate_boost]
    if not fate_parts:
        return None

    if not context.allow_fate_intervention:
        raise CommandValidationError(error_fate_not_available_here())
    # 1회 제한이 있는 자원이므로 한 커맨드에 두 번 붙이는 것 자체를 막는다.
    if len(fate_parts) > 1:
        raise CommandValidationError(error_fate_only_once_per_command())

    fate_part = fate_parts[0]
    if fate_part.type_ not in (ActionType.ATTACK, ActionType.SKILL):
        raise CommandValidationError(error_fate_unsupported_command())

    if user.status.revival_count < FATE_INTERVENTION_REQUIRED_REVIVAL_COUNT:
        raise CommandValidationError(
            error_fate_requires_revival(FATE_INTERVENTION_REQUIRED_REVIVAL_COUNT)
        )
    if user.fate_used:
        raise CommandValidationError(error_fate_already_used())
    # 체력 소모가 곧 전투불능을 뜻하지 않도록 "초과"를 요구한다.
    if user.status.curr_hp <= FATE_INTERVENTION_HP_COST:
        raise CommandValidationError(
            error_fate_not_enough_hp(FATE_INTERVENTION_HP_COST, user.status.curr_hp)
        )
    return fate_part


def _resolve_and_reject_companion_target(
    context: BattlefieldContext, target: "CharacterId | BattlefieldColumnIndex"
) -> "CharacterId | BattlefieldColumnIndex":
    if not isinstance(target, CharacterId):
        return target
    resolved = context.resolve_character_id(target)
    if resolved in context.companion_owners:
        raise CommandValidationError(error_target_is_companion(resolved))
    return resolved
