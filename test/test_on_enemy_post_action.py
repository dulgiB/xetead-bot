"""ON_ENEMY_POST_ACTION 타이밍 버프 — 적이 아군을 표시하고 POST에서 미이동 시 대미지."""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.models import BuffData
from battle.objects.define import BattlefieldColumnIndex, FactionType, ValueType
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectAddBuff
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


@pytest.fixture
def stationary_debuff_data() -> BuffData:
    """대상이 이동하지 않았을 때 POST_ACTION에 20 대미지를 입히는 디버프."""
    return BuffData(
        id="조준",
        buff_class_name="BuffConditionalDamage",
        duration_turn_value=1,
        duration_count_value=0,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=20,
        condition_="HolderDidNotMoveThisTurnCondition",
        condition_value=None,
        is_debuff=True,
        description="",
    )


@pytest.fixture
def marking_skill(stationary_debuff_data) -> SkillData:
    """PRE_ACTION에 아군 1명에게 '조준' 디버프를 거는 적군 스킬."""
    return SkillData(
        id="조준 사격",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id="조준",
                buff_add_timing=None,
                apply_timing=RoundPhaseType.ENEMY_PRE_ACTION,
            )
        ],
        description="",
    )


def _setup(stationary_debuff_data, marking_skill):
    ctx = BattlefieldContext(
        buff_dict={"조준": stationary_debuff_data},
        skill_dict={"조준 사격": marking_skill},
    )
    manager = RoundManager(ctx)  # 시작 시 ENEMY_PRE_ACTION

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1", skill_1_id="조준 사격"),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    return ctx, manager, ally_id, enemy_id


def test_ally_did_not_move_takes_damage(stationary_debuff_data, marking_skill):
    """아군이 이동하지 않으면 POST_ACTION에 대미지를 받아야 한다."""
    ctx, manager, ally_id, enemy_id = _setup(stationary_debuff_data, marking_skill)

    # PRE: 적군이 조준 사격 선언 → 아군에게 '조준' 디버프 적용
    cmd = parse_character_command(enemy_id, "[조준 사격/아군 1]", ctx)
    manager.process_command(cmd)

    initial_hp = ctx.characters[ally_id].status.curr_hp

    # ALLY_ACTION: 아군 이동 없음
    manager.to_phase(RoundPhaseType.ALLY_ACTION)

    # POST_ACTION: on_enemy_post_action() 발동 → 조건 충족 → 대미지
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.characters[ally_id].status.curr_hp == initial_hp - 20


def test_ally_moved_takes_no_damage(stationary_debuff_data, marking_skill):
    """아군이 이동하면 POST_ACTION 대미지를 받지 않아야 한다."""
    ctx, manager, ally_id, enemy_id = _setup(stationary_debuff_data, marking_skill)

    cmd = parse_character_command(enemy_id, "[조준 사격/아군 1]", ctx)
    manager.process_command(cmd)

    initial_hp = ctx.characters[ally_id].status.curr_hp

    # ALLY_ACTION: 아군이 이동
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    move_cmd = parse_character_command(ally_id, "[이동/3]", ctx)
    manager.process_command(move_cmd)

    # POST_ACTION: 조건 불충족 → 대미지 없음
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.characters[ally_id].status.curr_hp == initial_hp


def test_debuff_expires_after_one_round(stationary_debuff_data, marking_skill):
    """'조준' 디버프는 1턴이므로 라운드 종료 후 제거되어야 한다."""
    from battle.objects.define import BuffApplyTiming

    ctx, manager, ally_id, enemy_id = _setup(stationary_debuff_data, marking_skill)

    cmd = parse_character_command(enemy_id, "[조준 사격/아군 1]", ctx)
    manager.process_command(cmd)

    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

    # 다음 라운드에 디버프가 남아 있으면 안 됨
    remaining = ctx.buff_container.get_buffs_by(
        ally_id, BuffApplyTiming.ON_ENEMY_POST_ACTION
    )
    assert len(remaining) == 0


def test_target_removed_before_post_action_does_not_crash():
    """PRE에서 지목된 대상이 ALLY_ACTION 중 제거(사망)되어도 POST_ACTION 처리는
    KeyError 없이 안전하게 넘어가야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = RoundManager(ctx)  # 시작 시 ENEMY_PRE_ACTION

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    # PRE: 적군이 아군 1을 공격 선언 (대미지/힐은 POST에서 재전개되어 처리됨)
    cmd = parse_character_command(enemy_id, "[공격/아군 1]", ctx)
    manager.process_command(cmd)

    manager.to_phase(RoundPhaseType.ALLY_ACTION)

    # ALLY_ACTION 중 아군 1이 사망 처리되어 전장에서 제거됨
    ctx.remove_character(ally_id)

    # POST_ACTION: 이미 사라진 대상에 대한 재전개가 KeyError 없이 처리되어야 한다
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ally_id not in ctx.characters
