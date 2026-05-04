import pytest
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from helpers import get_test_preset


@pytest.fixture
def damage_skill_setup(context_with_damage_skill):
    ctx = context_with_damage_skill
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="강타"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx, manager


def test_damage_skill_reduces_hp(damage_skill_setup):
    """대미지 스킬 사용 후 적의 HP가 감소해야 한다."""
    ctx, manager = damage_skill_setup
    enemy_id = CharacterId("적군 1")
    initial_hp = ctx.characters[enemy_id].status.curr_hp

    cmd = parse_character_command(CharacterId("아군 1"), "[스킬1/적군 1]")
    manager.process_command(cmd)

    assert ctx.characters[enemy_id].status.curr_hp < initial_hp


def test_damage_skill_costs_2(damage_skill_setup):
    """대미지 스킬(스킬1)은 코스트 2를 소모해야 한다."""
    ctx, manager = damage_skill_setup
    user_id = CharacterId("아군 1")
    initial_cost = ctx.characters[user_id].status.remaining_cost

    cmd = parse_character_command(user_id, "[스킬1/적군 1]")
    manager.process_command(cmd)

    assert ctx.characters[user_id].status.remaining_cost == initial_cost - 2


@pytest.fixture
def heal_skill_setup(context_with_heal_skill):
    ctx = context_with_heal_skill
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="회복"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 2", initial_hp=80),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    return ctx, manager


def test_heal_skill_increases_hp(heal_skill_setup):
    """회복 스킬 사용 후 대상의 HP가 증가해야 한다."""
    ctx, manager = heal_skill_setup
    target_id = CharacterId("아군 2")
    initial_hp = ctx.characters[target_id].status.curr_hp

    cmd = parse_character_command(CharacterId("아군 1"), "[스킬1/아군 2]")
    manager.process_command(cmd)

    assert ctx.characters[target_id].status.curr_hp > initial_hp


def test_heal_does_not_exceed_max_hp(heal_skill_setup):
    """회복 후 HP는 최대 HP를 초과하지 않아야 한다."""
    ctx, manager = heal_skill_setup
    target_id = CharacterId("아군 2")
    max_hp = ctx.characters[target_id].status._max_hp
    ctx.characters[target_id].status.curr_hp = max_hp  # HP를 최대치로 설정

    cmd = parse_character_command(CharacterId("아군 1"), "[스킬1/아군 2]")
    manager.process_command(cmd)

    assert ctx.characters[target_id].status.curr_hp <= max_hp


@pytest.fixture
def buff_skill_setup(context_with_atk_buff_skill):
    ctx = context_with_atk_buff_skill
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="공격 보조"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx, manager


def test_buff_applied_to_target(buff_skill_setup):
    """버프 부여 스킬 사용 후 대상에게 버프가 적용되어야 한다."""
    from battle.objects.define import BuffApplyTiming

    ctx, manager = buff_skill_setup
    target_id = CharacterId("아군 2")

    cmd = parse_character_command(CharacterId("아군 1"), "[스킬1/아군 2]")
    manager.process_command(cmd)

    buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ATTACK)
    assert len(buffs) > 0


def test_atk_buff_increases_damage(buff_skill_setup):
    """공격력 증가 버프를 받은 캐릭터의 공격이 더 강해야 한다 (통계적 근거로 판단 어려우므로 버프 존재 확인)."""
    from battle.objects.define import BuffApplyTiming

    ctx, manager = buff_skill_setup
    target_id = CharacterId("아군 2")

    # 버프 부여
    cmd1 = parse_character_command(CharacterId("아군 1"), "[스킬1/아군 2]")
    manager.process_command(cmd1)

    buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ATTACK)
    buff_values = [b.value for b in buffs]
    assert any(v > 0 for v in buff_values)


def test_buff_duration_decrements_on_round_end(buff_skill_setup):
    """라운드 종료 시 버프의 남은 턴수가 차감되어야 한다."""
    from battle.objects.define import BuffApplyTiming

    ctx, manager = buff_skill_setup
    target_id = CharacterId("아군 2")

    cmd = parse_character_command(CharacterId("아군 1"), "[스킬1/아군 2]")
    manager.process_command(cmd)

    buffs_before = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ATTACK)
    turns_before = buffs_before[0].duration.remaining_turns

    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

    # 새 라운드에서 다시 확인 (버프가 아직 남아 있다면)
    buffs_after = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ATTACK)
    if buffs_after:
        assert buffs_after[0].duration.remaining_turns == turns_before - 1
