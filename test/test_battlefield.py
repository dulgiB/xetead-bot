import pytest
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from helpers import get_test_preset


def test_add_and_remove_character(empty_context):
    """캐릭터를 추가하고 제거했을 때 전장이 빈 상태로 돌아오는지 확인."""
    empty_context.add_character(
        get_test_preset("테스트"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    assert CharacterId("테스트") in empty_context.characters

    empty_context.remove_character(CharacterId("테스트"))
    assert CharacterId("테스트") not in empty_context.characters


def test_remove_nonexistent_character_raises(empty_context):
    """존재하지 않는 캐릭터를 제거하면 CommandValidationError가 발생해야 한다."""
    with pytest.raises(CommandValidationError):
        empty_context.remove_character(CharacterId("없는캐릭터"))


def test_column_overflow_raises(empty_context):
    """한 열에 CHARACTER_PER_COLUMN(3명)을 초과하면 CommandValidationError."""
    from battle.core.battlefield_context import CHARACTER_PER_COLUMN

    for i in range(CHARACTER_PER_COLUMN):
        empty_context.add_character(
            get_test_preset(f"캐릭터{i}"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
    with pytest.raises(CommandValidationError):
        empty_context.add_character(
            get_test_preset("초과"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )


@pytest.fixture
def battle_setup(empty_context):
    """아군 1명, 적군 1명이 같은 열에 배치된 전장과 매니저를 반환."""
    manager = RoundManager(empty_context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    empty_context.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    empty_context.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return empty_context, manager


def test_basic_attack_reduces_hp(battle_setup):
    """기본 공격 후 적군의 HP가 감소해야 한다."""
    context, manager = battle_setup
    enemy_id = CharacterId("적군 1")
    initial_hp = context.characters[enemy_id].status.curr_hp

    cmd = parse_character_command(CharacterId("아군 1"), "[공격/적군 1]")
    manager.process_command(cmd)

    assert context.characters[enemy_id].status.curr_hp < initial_hp


def test_basic_attack_wrong_phase_raises(empty_context):
    """ENEMY_PRE_ACTION 페이즈에서 아군이 공격하면 CommandValidationError."""
    manager = RoundManager(empty_context)
    # 페이즈 전환 없이 기본 상태(ENEMY_PRE_ACTION)로 시작
    empty_context.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    empty_context.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    cmd = parse_character_command(CharacterId("아군 1"), "[공격/적군 1]")
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)


def test_attack_out_of_range_raises(empty_context):
    """사거리 밖의 적을 공격하면 CommandValidationError."""
    manager = RoundManager(empty_context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    # 사거리 1짜리 캐릭터를 1열에 배치하고 적을 7열에 배치
    empty_context.add_character(
        get_test_preset("아군 1", attack_range=1)
        if hasattr(get_test_preset("x"), "attack_range")
        else get_test_preset("아군 1"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    empty_context.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(6)
    )
    cmd = parse_character_command(CharacterId("아군 1"), "[공격/적군 1]")
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)


def test_hp_does_not_go_below_zero(battle_setup):
    """HP는 0 미만으로 내려가지 않아야 한다."""
    context, manager = battle_setup
    enemy_id = CharacterId("적군 1")
    context.characters[enemy_id].status.curr_hp = 1  # HP를 1로 강제 설정

    cmd = parse_character_command(CharacterId("아군 1"), "[공격/적군 1]")
    manager.process_command(cmd)

    assert context.characters[enemy_id].status.curr_hp >= 0


def test_cost_deducted_after_action(battle_setup):
    """행동 후 코스트가 차감되어야 한다."""
    context, manager = battle_setup
    user_id = CharacterId("아군 1")
    initial_cost = context.characters[user_id].status.remaining_cost

    cmd = parse_character_command(user_id, "[공격/적군 1]")
    manager.process_command(cmd)

    assert context.characters[user_id].status.remaining_cost < initial_cost


def test_insufficient_cost_raises(battle_setup):
    """코스트가 부족하면 CommandValidationError가 발생해야 한다."""
    context, manager = battle_setup
    user_id = CharacterId("아군 1")
    context.characters[user_id].status.remaining_cost = 0  # 코스트 고갈

    cmd = parse_character_command(user_id, "[공격/적군 1]")
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)
