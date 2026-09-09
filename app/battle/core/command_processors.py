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
    ItemType,
)
from battle.objects.extensions import get_total_cost
from battle.objects.models import CharacterId, ValueWithModifiers

if TYPE_CHECKING:
    from battle.core.round_manager import RoundManager
    from battle.objects.character.combat_character import CombatCharacter


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

    # 코스트 차감 - 검증 통과 후 실제 처리 시점에 차감
    user = context.characters[command.user_id]
    user.status.remaining_cost -= needed_cost

    # 운명간섭 대가(체력 20) - 커맨드가 실제로 처리된 뒤에만 소모한다
    _apply_fate_intervention_cost(user, command, results_per_part)

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

    # 운명간섭 대가도 코스트와 같이 선언 시점에 소모한다 — 적군 진영에 배치된
    # 캐릭터 시트 출신 캐릭터(`[배치/이름/적군 N열]`)가 여기로 오면, POST에서
    # 소모하려 하면 재전개마다 중복 소모되거나 아예 누락된다.
    _apply_fate_intervention_cost(user, command, results_per_part)

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

    # 체력이 0 이하인 캐릭터는 행동을 선언할 수 없다. 아군은 체력이 0이 되어도
    # 부활 여지 때문에 필드에서 자동 제거되지 않으므로(_remove_eliminated_characters
    # 참고) 이 검증이 없으면 전투불능 상태에서 그대로 커맨드가 통과한다.
    # "대상으로 지정되는 것"은 여전히 허용된다 — 여기서 막는 건 행동 주체뿐이다.
    if user.status.curr_hp <= 0:
        raise CommandValidationError(error_character_is_defeated(command.user_id))

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

    fate_part = _validate_fate_boost(context, user, command)

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
            item_type = context.get_item_data_by_id(part.item_id).item_type
            if item_type not in (ItemType.CONSUMABLE, ItemType.BATTLE_CONSUMABLE):
                raise CommandValidationError(error_item_not_usable_in_battle())
            if context.inventory.get_count(command.user_id.name, part.item_id) <= 0:
                raise CommandValidationError(error_no_item_in_inventory(part.item_id))
            if context.get_item_data_by_id(part.item_id).effect is None:
                raise CommandValidationError(error_item_has_no_effect())

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

    # 스킬 운명간섭은 "대미지 스킬"에만 적용된다. 실제로 대미지가 나오는지는
    # 전개해 봐야 알 수 있으므로(효과 구현체마다 다름) 전개 후에 확인한다 —
    # 여기서 걸리면 코스트도 체력도 아직 소모되지 않은 상태로 중단된다.
    if fate_part is not None and fate_part.type_ == ActionType.SKILL:
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
            source_labels=("운명간섭",),
        )
    )


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
