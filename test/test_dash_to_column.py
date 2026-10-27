"""열 지정 돌진(SkillEffectDashToColumn)과, 출발 열을 읽는 경로 광역 효과가
커맨드 전개 시점의 출발 위치를 제대로 보는지에 대한 테스트.

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/스킬명 대신 일반화된 이름을 쓴다.
"""

from typing import Optional

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.buff.models import BuffData
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectDamage,
    SkillEffectDashToColumn,
    SkillEffectMove,
    SkillEffectSplashAlongPath,
)
from battle.objects.skill.effects.effect_dash_to_column import dash_path_columns
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

DASHER = CharacterId("돌진자")


def _dash_skill(apply_timing: Optional[RoundPhaseType] = None) -> SkillData:
    return SkillData(
        id="DashSkill",
        target_rule="SkillTargetRuleColumn",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDashToColumn(
                ValueSourceType.FIXED,
                10,
                ValueType.INTEGER,
                None,
                None,
                apply_timing=apply_timing,  # type: ignore[arg-type]
            )
        ],
        description="",
    )


def _taunt_buff() -> BuffData:
    return BuffData(
        id="도발",
        description="",
        buff_class_name="BuffTaunt",
        duration_turn_value=1,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=None,
        value=None,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.DEBUFF,
    )


def _context(skill: SkillData) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={"도발": _taunt_buff()}, skill_dict={skill.id: skill}
    )


def _add(
    ctx: BattlefieldContext,
    name: str,
    faction: FactionType,
    column: int,
    **kwargs,
) -> CharacterId:
    ctx.add_character(
        get_test_preset(name, **kwargs), faction, BattlefieldColumnIndex(column)
    )
    return CharacterId(name)


def _hp(ctx: BattlefieldContext, name: str) -> int:
    return ctx.characters[CharacterId(name)].status.curr_hp


def _ally_battle(
    dasher_column: int = 0, attack_range: int = 3
) -> tuple[BattlefieldContext, RoundManager]:
    ctx = _context(_dash_skill())
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    _add(
        ctx,
        DASHER.name,
        FactionType.ALLY,
        dasher_column,
        skill_1_id="DashSkill",
        attack_range=attack_range,
    )
    return ctx, manager


def test_path_columns_include_departure_and_destination():
    path = dash_path_columns(BattlefieldColumnIndex(1), BattlefieldColumnIndex(4), 1)
    assert [c.value for c in path] == [1, 2, 3, 4]
    path = dash_path_columns(BattlefieldColumnIndex(4), BattlefieldColumnIndex(1), 1)
    assert [c.value for c in path] == [1, 2, 3, 4]


def test_multi_column_dasher_sweeps_every_column_it_occupies_on_the_way():
    # 1~2열에서 3~4열로: 출발 때 차지한 열부터 도착해 차지한 열까지 전부.
    path = dash_path_columns(BattlefieldColumnIndex(0), BattlefieldColumnIndex(2), 2)
    assert [c.value for c in path] == [0, 1, 2, 3]


def test_dash_into_empty_column_hits_every_foe_on_the_path_equally():
    ctx, manager = _ally_battle(dasher_column=0)
    _add(ctx, "적 1", FactionType.ENEMY, 1)
    _add(ctx, "적 2", FactionType.ENEMY, 2)
    _add(ctx, "적 3", FactionType.ENEMY, 2)
    _add(ctx, "출발열 적", FactionType.ENEMY, 0)
    _add(ctx, "경로 밖 적", FactionType.ENEMY, 4)

    # 4열(index 3)은 비어 있다.
    manager.process_command(parse_character_command(DASHER, "[DashSkill/4열]", ctx))

    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(3)
    assert _hp(ctx, "적 1") == 90
    assert _hp(ctx, "적 2") == 90
    assert _hp(ctx, "적 3") == 90
    assert _hp(ctx, "출발열 적") == 90
    assert _hp(ctx, "경로 밖 적") == 100


def test_dash_with_nobody_on_the_path_just_moves():
    ctx, manager = _ally_battle(dasher_column=0)
    manager.process_command(parse_character_command(DASHER, "[DashSkill/3열]", ctx))

    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(2)
    assert ctx.characters[DASHER].status.remaining_cost == 1


def test_dash_beyond_range_is_rejected_without_spending_cost():
    ctx, manager = _ally_battle(dasher_column=0, attack_range=2)
    _add(ctx, "적 1", FactionType.ENEMY, 1)

    with pytest.raises(CommandValidationError):
        manager.process_command(parse_character_command(DASHER, "[DashSkill/4열]", ctx))

    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(0)
    assert ctx.characters[DASHER].status.remaining_cost == 3
    assert _hp(ctx, "적 1") == 100


def test_dash_to_own_column_is_rejected():
    ctx, manager = _ally_battle(dasher_column=2)

    with pytest.raises(CommandValidationError):
        manager.process_command(parse_character_command(DASHER, "[DashSkill/3열]", ctx))


def test_character_target_is_rejected():
    ctx, manager = _ally_battle(dasher_column=0)
    _add(ctx, "적 1", FactionType.ENEMY, 1)

    with pytest.raises(CommandValidationError):
        manager.process_command(
            parse_character_command(DASHER, "[DashSkill/적 1]", ctx)
        )


def test_path_starts_after_an_earlier_move_in_the_same_command():
    ctx, manager = _ally_battle(dasher_column=0, attack_range=2)
    _add(ctx, "이동 전 열 적", FactionType.ENEMY, 0)
    _add(ctx, "적 1", FactionType.ENEMY, 1)
    _add(ctx, "적 2", FactionType.ENEMY, 3)

    # 2열로 옮긴 뒤 4열로 돌진: 경로는 2~4열이고 이동 전의 1열은 빠진다.
    manager.process_command(
        parse_character_command(DASHER, "[이동/2열 - DashSkill/4열]", ctx)
    )

    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(3)
    assert _hp(ctx, "이동 전 열 적") == 100
    assert _hp(ctx, "적 1") == 90
    assert _hp(ctx, "적 2") == 90


def test_multi_column_foe_on_the_path_is_hit_per_overlapping_column():
    ctx, manager = _ally_battle(dasher_column=0)
    _add(ctx, "거대 적", FactionType.ENEMY, 1, span=2)

    manager.process_command(parse_character_command(DASHER, "[DashSkill/4열]", ctx))

    assert _hp(ctx, "거대 적") == 80


def test_taunt_does_not_redirect_the_path_damage():
    ctx, manager = _ally_battle(dasher_column=0)
    _add(ctx, "적 1", FactionType.ENEMY, 1)
    taunter = _add(ctx, "도발자", FactionType.ENEMY, 5)
    ctx.buff_container.add(
        BuffAddData(given_by=taunter, applied_to=DASHER, buff_id="도발")
    )

    manager.process_command(parse_character_command(DASHER, "[DashSkill/3열]", ctx))

    assert _hp(ctx, "적 1") == 90
    assert _hp(ctx, "도발자") == 100


def _enemy_battle(
    apply_timing: Optional[RoundPhaseType] = None,
) -> tuple[BattlefieldContext, RoundManager]:
    ctx = _context(_dash_skill(apply_timing))
    manager = RoundManager(ctx)
    _add(
        ctx,
        DASHER.name,
        FactionType.ENEMY,
        0,
        skill_1_id="DashSkill",
        attack_range=3,
    )
    _add(ctx, "아군 1", FactionType.ALLY, 1)
    _add(ctx, "아군 2", FactionType.ALLY, 3)
    _add(ctx, "아군 3", FactionType.ALLY, 5)
    return ctx, manager


def test_enemy_moves_on_declaration_and_hits_the_path_from_where_it_started():
    ctx, manager = _enemy_battle()
    _add(ctx, "출발 열 아군", FactionType.ALLY, 0)
    manager.process_command(parse_character_command(DASHER, "[DashSkill/4열]", ctx))

    # 선언 때 이미 도착 열에 있다.
    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(3)
    assert _hp(ctx, "아군 1") == 100

    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    # 정산 때는 이미 떠났지만 선언 직전에 서 있던 열도 경로다.
    assert _hp(ctx, "출발 열 아군") == 90
    assert _hp(ctx, "아군 1") == 90
    assert _hp(ctx, "아군 2") == 90
    assert _hp(ctx, "아군 3") == 100


def test_ally_that_leaves_the_path_before_resolution_is_not_hit():
    ctx, manager = _enemy_battle()
    manager.process_command(parse_character_command(DASHER, "[DashSkill/4열]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.process_command(
        parse_character_command(CharacterId("아군 1"), "[이동/5열]", ctx)
    )
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert _hp(ctx, "아군 1") == 100
    assert _hp(ctx, "아군 2") == 90


def test_enemy_dash_resolved_entirely_on_post_action():
    ctx, manager = _enemy_battle(apply_timing=RoundPhaseType.ENEMY_POST_ACTION)
    manager.process_command(parse_character_command(DASHER, "[DashSkill/4열]", ctx))

    # 선언 때는 움직이지 않는다 — 정산 때 돌진한다.
    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(0)

    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(3)
    assert _hp(ctx, "아군 1") == 90
    assert _hp(ctx, "아군 2") == 90


def test_enemy_target_dash_keeps_its_path_splash_until_resolution():
    """기존 돌진(상대의 현재 위치 + 경로 광역)도 에너미가 선언 때 이동하고
    정산 때 경로 대미지를 재전개하므로, 출발 열을 선언 직전 위치로 봐야
    경로상 아군이 맞는다."""
    skill = SkillData(
        id="DashSkill",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectMove(
                ValueSourceType.TARGET_CURR_POSITION, None, None, None, None
            ),
            SkillEffectDamage(ValueSourceType.FIXED, 30, ValueType.INTEGER, None, None),
            SkillEffectSplashAlongPath(
                ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
            ),
        ],
        description="",
    )
    ctx = _context(skill)
    manager = RoundManager(ctx)
    _add(ctx, DASHER.name, FactionType.ENEMY, 0, skill_1_id="DashSkill")
    _add(ctx, "주대상", FactionType.ALLY, 3)
    _add(ctx, "경로", FactionType.ALLY, 1)

    manager.process_command(parse_character_command(DASHER, "[DashSkill/주대상]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert _hp(ctx, "주대상") == 70
    assert _hp(ctx, "경로") == 90


def test_attack_after_a_dash_resolved_on_post_action_is_ranged_from_the_landing():
    """정산 때 돌진하는 스킬 뒤에 붙인 공격은 선언 때 도착 열에서 사거리를
    검증받았으므로, 정산 때도 도착 열에서 재야 한다."""
    ctx = _context(_dash_skill(apply_timing=RoundPhaseType.ENEMY_POST_ACTION))
    manager = RoundManager(ctx)
    _add(
        ctx,
        DASHER.name,
        FactionType.ENEMY,
        0,
        skill_1_id="DashSkill",
        attack_range=1,
        max_cost=3,
    )
    _add(ctx, "먼 아군", FactionType.ALLY, 2)

    manager.process_command(
        parse_character_command(DASHER, "[DashSkill/2열 - 공격/먼 아군]", ctx)
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(1)
    assert _hp(ctx, "먼 아군") < 100
