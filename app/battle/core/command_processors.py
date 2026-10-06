from datetime import date
from dataclasses import replace
from typing import TYPE_CHECKING, Optional

from utils.battle_helpers import columns_for_span, is_reachable_between

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
    error_keyword_already_used,
    error_keyword_not_available_here,
    error_keyword_not_enough_hp,
    error_keyword_only_once_per_command,
    error_keyword_requires_revival,
    error_keyword_skill_without_damage,
    error_keyword_unsupported_command,
    error_item_does_not_exist,
    error_item_has_no_effect,
    error_item_not_usable_here,
    error_item_not_usable_in_battle,
    error_no_item_in_inventory,
    error_no_remaining_cost,
    error_skill_not_registered,
    error_span_out_of_board,
    error_target_does_not_exist,
    error_too_many_characters,
    error_too_many_targets,
)
from battle.objects.define import (
    KEYWORD_BOOST_HP_COST,
    KEYWORD_BOOST_REQUIRED_REVIVAL_COUNT,
    ActionType,
    BattlefieldColumnIndex,
    CombatStatType,
    KeywordBoostMode,
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
    _apply_keyword_boost_cost(context, user, command, results_per_part)
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

    # 키워드 보정 대가도 코스트와 같이 선언 시점에 소모한다 — POST에서 소모하면
    # 재전개마다 중복 소모되거나 아예 누락된다.
    _apply_keyword_boost_cost(context, user, command, results_per_part)

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
    for calculator, post_part in zip(calculators, post_parts):
        _drop_targets_out_of_range(context, user_id, post_part, calculator)
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


def _drop_targets_out_of_range(
    context: BattlefieldContext,
    user_id: CharacterId,
    part_data: CommandPartData,
    calculator: CommandPartCalculator,
) -> None:
    """PRE 선언 뒤 아군 행동으로 사거리 밖에 놓인 대상을 POST 대미지에서 뺀다.

    사거리는 선언 시점에만 검증되므로, 여기서 다시 보지 않으면 밀려나거나
    스스로 물러난 대상도 그대로 맞는다. 그 대상에게 걸릴 부가 효과(디버프
    부여·스택 소모)도 같은 공격의 일부라 함께 뺀다. 도발 리다이렉트보다 먼저
    걸러, 빗나간 공격을 도발자가 끌어오지 않게 한다.

    POST 타이밍 effect의 이동은 계산 중에 일어나므로, PRE 검증과 같이
    시전자의 이동 목적지를 이어받아 판정한다.
    """
    user = context.characters[user_id]
    user_pos = context.find_character_position(user_id)
    attack_range = _effective_attack_range(context, user, part_data.original_part)

    for mutable in calculator.data_by_effect:
        if not calculator._damage_processed_in_phase(
            mutable.apply_timing, RoundPhaseType.ENEMY_POST_ACTION
        ):
            continue
        for move_data in mutable.move_list:
            if move_data.character_id == user_id:
                user_pos = move_data.to_position
        out_of_range: list[CharacterId] = []
        for damage_calc in mutable.damage_data_list:
            target_id = damage_calc.base.target_id
            if target_id in out_of_range or target_id not in context.characters:
                continue
            # 시전자는 선언한 이동 목적지 기준이라 위치에서 점유 열을 다시
            # 만들고, 대상은 전장에 있는 그대로의 점유 열을 쓴다.
            if not is_reachable_between(
                columns_for_span(user_pos, user.span),
                context.find_character_columns(target_id),
                attack_range,
            ):
                out_of_range.append(target_id)
        if not out_of_range:
            continue

        mutable.damage_data_list = [
            d for d in mutable.damage_data_list if d.base.target_id not in out_of_range
        ]
        mutable.buff_add_data_list = [
            d for d in mutable.buff_add_data_list if d.applied_to not in out_of_range
        ]
        mutable.buff_remove_data_list = [
            d
            for d in mutable.buff_remove_data_list
            if d.base.applied_to not in out_of_range
        ]
        mutable.nullified_effect_list.extend(
            (target_id, "사거리 밖, 대미지 없음") for target_id in out_of_range
        )


def _effective_attack_range(
    context: BattlefieldContext,
    user: "CombatCharacter",
    original_part: Optional[CommandPart],
) -> int:
    if (
        original_part is not None
        and original_part.type_ == ActionType.USE_ITEM
        and original_part.item_id is not None
    ):
        return context.get_item_data_by_id(original_part.item_id).attack_range
    return user.status[CombatStatType.RANGE]


def try_expansion_if_valid(
    context: BattlefieldContext, command: CharacterCommand
) -> tuple[list[CommandPartData], int]:
    """
    커맨드 실행 전 사전 검증. 문제가 있으면 CommandValidationError를 raise한다.
    검증 항목:
      1. 커맨드 사용자가 전장에 존재하는지
      2. 커맨드 사용자의 체력이 0보다 큰지 (행동 주체 기준. 진영 무관)
      3. 코스트가 충분한지
      4. 이동 목적지에 자리가 남아있는지 (이동 후 user_pos 갱신)
      5. 공격/스킬 대상이 전장에 존재하고 사거리 내인지 (갱신된 위치 기준)
      6. 키워드 보정("+")을 붙였다면 그 사용 조건을 만족하는지
    """

    if command.user_id not in context.characters:
        raise CommandValidationError(error_target_does_not_exist(command.user_id))

    user = context.characters[command.user_id]

    # 아군은 체력이 0이어도 부활 여지 때문에 필드에 남으므로, 행동 주체만
    # 여기서 막는다 — 대상으로 지정되는 것은 여전히 허용된다.
    if user.status.curr_hp <= 0:
        raise CommandValidationError(error_character_is_defeated())

    user_pos = context.find_character_position(command.user_id)

    # 입력한 공백이 등록된 표기와 달라도("스킬_1" vs "스킬 _1") 등록된 표기로
    # 치환해, 이후 검증·전개가 정확한 값을 보게 한다.
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
            targets=[_resolve_target(context, t) for t in part.targets],
        )
        for part in command.parts
    ]

    keyword_part = _validate_keyword_boost(context, user, command)

    for part in command.parts:
        if part.type_ == ActionType.SKILL and part.skill_id is not None:
            skill = next((s for s in user.skills if s.data.id == part.skill_id), None)
            if skill is None:
                raise CommandValidationError(error_skill_not_registered(part.skill_id))
            # "대상 추가" 모드는 "+"를 붙였을 때만 대상을 더 지정할 수 있게 한다.
            if skill.target_rule.target_count_is_area:
                allowed_target_count = 1
            else:
                allowed_target_count = skill.data.target_count + (
                    skill.data.keyword_boost_value
                    if part is keyword_part
                    and skill.data.keyword_mode is KeywordBoostMode.EXTRA_TARGET
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
        effective_range = _effective_attack_range(
            context, user, command_data.original_part
        )

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
                mover = context.characters[mover_id]
                if len(columns_for_span(to_pos, mover.span)) < mover.span:
                    raise CommandValidationError(
                        error_span_out_of_board(to_pos, mover.span)
                    )
                if (
                    context.try_find_empty_slot(
                        mover.faction, to_pos, span=mover.span, ignore=mover_id
                    )
                    is None
                ):
                    raise CommandValidationError(error_too_many_characters(to_pos))
                if mover_id == command.user_id:
                    user_pos = to_pos

            for damage_data in sub_data.damage_list:
                target_id = damage_data.target_id
                if target_id not in context.characters:
                    raise CommandValidationError(error_target_does_not_exist(target_id))

                if not is_reachable_between(
                    columns_for_span(user_pos, user.span),
                    context.find_character_columns(target_id),
                    effective_range,
                ):
                    raise CommandValidationError(
                        error_attack_position_too_far(
                            context.find_character_position(target_id)
                        )
                    )

            for heal_data in sub_data.heal_list:
                target_id = heal_data.target_id
                if target_id not in context.characters:
                    raise CommandValidationError(error_target_does_not_exist(target_id))

    # keyword_mode가 없는 스킬은 굴림 보정을 받을 대미지가 있는 스킬에만 키워드
    # 보정을 허용한다. 대미지가 실제로 나오는지는 효과 구현체마다 달라 전개해 봐야
    # 알 수 있다.
    if (
        keyword_part is not None
        and keyword_part.type_ == ActionType.SKILL
        and _keyword_skill_data(user, keyword_part).keyword_mode is None
    ):
        assert keyword_part.skill_id is not None
        has_damage = any(
            damage.value.takes_keyword_roll_bonus
            for command_data in expanded_command_data_list
            if command_data.original_part is keyword_part
            for sub_data in command_data.data_per_effect
            if sub_data is not None
            for damage in sub_data.damage_list
        )
        if not has_damage:
            raise CommandValidationError(
                error_keyword_skill_without_damage(keyword_part.skill_id)
            )

    return expanded_command_data_list, needed_cost


def _apply_keyword_boost_cost(
    context: BattlefieldContext,
    user: "CombatCharacter",
    command: CharacterCommand,
    results_per_part: list[CommandPartProcessResult],
) -> None:
    """키워드 보정을 쓴 커맨드라면 체력을 소모하고 "이번 진행에 사용함"을 표시한다.

    소모량은 대미지 계산 파이프라인을 타지 않는 순수 자원 소비다 — 반사/방어
    버프가 개입하거나 "피격" 반응형 버프가 발동해서는 안 되기 때문이다. 대신
    답글·시트 반영이 기존 경로를 그대로 타도록 대미지 로그 엔트리 형태로
    결과에 얹는다(로그 엔트리의 `result`를 보고 체력을 write-back하는
    `bot/log_sheets.py`의 write_back_changed_hp() 참고).

    어느 체력에서 빼는지는 전장이 정한다(`pay_keyword_cost_hp()`) — 결투는
    임시 체력이 아니라 시트의 실제 체력에서 뺀다.
    """
    if not any(part.keyword_boost for part in command.parts):
        return
    if not results_per_part:
        return

    hp_after, max_hp, hp_is_persistent = context.pay_keyword_cost_hp(user)
    user.keyword_date = date.today().isoformat()
    results_per_part[-1].log_entries.append(
        BattleLogEntry(
            target_name=user.id.name,
            kind=BattleLogEntryKind.DAMAGE,
            result=f"대미지 {KEYWORD_BOOST_HP_COST}",
            value=KEYWORD_BOOST_HP_COST,
            hp_after=hp_after,
            max_hp=max_hp,
            source_labels=("키워드 보정",),
            hp_is_persistent=hp_is_persistent,
        )
    )


def _keyword_skill_data(user: "CombatCharacter", part: CommandPart) -> "SkillData":
    """키워드 보정이 붙은 스킬 파트의 SkillData. 스킬 등록 여부는 이 함수를 부르기
    전에 이미 검증돼 있다(error_skill_not_registered)."""
    skill = next((s for s in user.skills if s.data.id == part.skill_id), None)
    assert skill is not None
    return skill.data


def _validate_keyword_boost(
    context: BattlefieldContext, user: "CombatCharacter", command: CharacterCommand
) -> Optional[CommandPart]:
    """키워드 보정("+") 선언의 사전 조건을 검증하고, 대상 파트를 반환한다.

    "+"가 없으면 None을 반환한다. 대미지 스킬 여부는 커맨드를 전개해 봐야
    알 수 있어 여기서 확인하지 않는다 (try_expansion_if_valid 후반부 참고).
    """
    keyword_parts = [part for part in command.parts if part.keyword_boost]
    if not keyword_parts:
        return None

    if not context.allow_keyword_boost:
        raise CommandValidationError(error_keyword_not_available_here())
    # 1회 제한이 있는 자원이므로 한 커맨드에 두 번 붙이는 것 자체를 막는다.
    if len(keyword_parts) > 1:
        raise CommandValidationError(error_keyword_only_once_per_command())

    keyword_part = keyword_parts[0]
    if keyword_part.type_ not in (ActionType.ATTACK, ActionType.SKILL):
        raise CommandValidationError(error_keyword_unsupported_command())

    if user.status.revival_count < KEYWORD_BOOST_REQUIRED_REVIVAL_COUNT:
        raise CommandValidationError(
            error_keyword_requires_revival(KEYWORD_BOOST_REQUIRED_REVIVAL_COUNT)
        )
    if user.keyword_used:
        raise CommandValidationError(error_keyword_already_used())
    # 체력 소모가 곧 전투불능을 뜻하지 않도록 "초과"를 요구한다.
    available_hp = context.keyword_cost_hp(user)
    if available_hp <= KEYWORD_BOOST_HP_COST:
        raise CommandValidationError(
            error_keyword_not_enough_hp(
                KEYWORD_BOOST_HP_COST,
                None if user.hide_hp else available_hp,
            )
        )
    return keyword_part


def _resolve_target(
    context: BattlefieldContext, target: "CharacterId | BattlefieldColumnIndex"
) -> "CharacterId | BattlefieldColumnIndex":
    if not isinstance(target, CharacterId):
        return target
    return context.resolve_character_id(target)
