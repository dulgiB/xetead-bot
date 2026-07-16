"""
개체+인접열 동시 지정 스킬(코스트 2) 관련 테스트.

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/스킬명 대신 일반화된 이름을 쓴다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectMove
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


@pytest.fixture
def cost2_skill() -> SkillData:
    """대상에게 공격 굴림 180% 대미지, 지정한 인접 열로 대상을 강제 이동."""
    return SkillData(
        id="Cost2Skill",
        target_rule="SkillTargetRuleNamedWithColumn",
        target_count=2,
        cost=2,
        effects=[
            SkillEffectDamage(
                ValueSourceType.STAT_ATK_ROLL, 180, ValueType.PERCENT, None, None
            ),
            SkillEffectMove(ValueSourceType.INPUT_COLUMN, None, None, None, None),
        ],
        description="",
    )


def _make_manager(cost2_skill) -> tuple[BattlefieldContext, RoundManager]:
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"Cost2Skill": cost2_skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return ctx, manager


def test_deals_damage_and_moves_target_to_specified_adjacent_column(cost2_skill):
    """열을 함께 지정하면 대상에게 대미지를 입히고 지정한 열로 이동시켜야 한다."""
    ctx, manager = _make_manager(cost2_skill)
    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="Cost2Skill"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    # 적군: COL3(2) → 인접 열은 COL2(1) 또는 COL4(3)
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(2)
    )

    cmd = parse_character_command(ally_id, "[Cost2Skill/적군 1/4열]", ctx)
    manager.process_command(cmd)

    assert ctx.find_character_position(enemy_id) == BattlefieldColumnIndex(3)
    assert ctx.characters[enemy_id].status.curr_hp < 100


def test_can_target_ally_for_damage_and_repositioning(cost2_skill):
    """대상 진영에 제한이 없어야 한다 — 아군을 대상으로 지정해도 적과 동일하게
    대미지를 입히고 지정한 인접 열로 이동시켜야 한다."""
    ctx, manager = _make_manager(cost2_skill)
    caster_id = CharacterId("아군 1")
    ally_target_id = CharacterId("아군 2")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="Cost2Skill"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    # 아군 대상: COL3(2) → 인접 열은 COL2(1) 또는 COL4(3)
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(2)
    )

    cmd = parse_character_command(caster_id, "[Cost2Skill/아군 2/4열]", ctx)
    manager.process_command(cmd)

    assert ctx.find_character_position(ally_target_id) == BattlefieldColumnIndex(3)
    assert ctx.characters[ally_target_id].status.curr_hp < 100


def test_omitting_column_deals_damage_without_moving(cost2_skill):
    """열을 생략하면 대미지만 입히고 이동은 발생하지 않아야 한다."""
    ctx, manager = _make_manager(cost2_skill)
    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="Cost2Skill"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(2)
    )

    cmd = parse_character_command(ally_id, "[Cost2Skill/적군 1]", ctx)
    manager.process_command(cmd)

    assert ctx.find_character_position(enemy_id) == BattlefieldColumnIndex(2)
    assert ctx.characters[enemy_id].status.curr_hp < 100


def test_non_adjacent_column_is_rejected(cost2_skill):
    """대상의 현재 위치 기준으로 인접(±1)하지 않은 열을 지정하면 검증에서 실패해야 한다."""
    ctx, manager = _make_manager(cost2_skill)
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="Cost2Skill"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    # 적군: COL3(2) → COL7(6)은 인접하지 않음
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(2)
    )

    cmd = parse_character_command(ally_id, "[Cost2Skill/적군 1/7열]", ctx)
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)


def test_two_character_targets_is_rejected(cost2_skill):
    """캐릭터 대상을 2개 지정하는 등 잘못된 조합은 거부되어야 한다."""
    ctx, manager = _make_manager(cost2_skill)
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="Cost2Skill"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(2)
    )
    ctx.add_character(
        get_test_preset("적군 2"), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )

    cmd = parse_character_command(ally_id, "[Cost2Skill/적군 1/적군 2]", ctx)
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)
