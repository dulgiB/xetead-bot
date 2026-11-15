"""돌진·자신을 옮기는 강제 이동 뒤에 붙은 파트가 그 목적지를 이어받는지에 대한
테스트(코스트·사거리·이동 기준 위치).

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/스킬명 대신 일반화된 이름을 쓴다.
"""

import pytest

from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import try_expansion_if_valid
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    BattlefieldColumnIndex,
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
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

USER = CharacterId("시전자")

TARGET_DASH = SkillData(
    id="TargetDash",
    target_rule="SkillTargetRuleNamed",
    target_count=1,
    cost=1,
    effects=[
        SkillEffectMove(ValueSourceType.TARGET_CURR_POSITION, None, None, None, None),
        SkillEffectDamage(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None),
        SkillEffectSplashAlongPath(
            ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None
        ),
    ],
    description="",
)

COLUMN_DASH = SkillData(
    id="ColumnDash",
    target_rule="SkillTargetRuleColumn",
    target_count=1,
    cost=1,
    effects=[
        SkillEffectDashToColumn(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
    ],
    description="",
)

# 캐릭터 하나와 인접한 열 하나를 받아 그 캐릭터를 열로 옮긴다(시전자 지정 가능).
THROW = SkillData(
    id="Throw",
    target_rule="SkillTargetRuleNamedWithColumn",
    target_count=2,
    cost=1,
    effects=[SkillEffectMove(ValueSourceType.INPUT_COLUMN, None, None, None, None)],
    description="",
)

PULL = SkillData(
    id="Pull",
    target_rule="SkillTargetRuleNamed",
    target_count=1,
    cost=1,
    effects=[
        SkillEffectMove(ValueSourceType.SELF_CURR_POSITION, None, None, None, None)
    ],
    description="",
)

SKILLS = (TARGET_DASH, COLUMN_DASH, THROW, PULL)


def _setup(user_column: int, attack_range: int = 3) -> BattlefieldContext:
    ctx = BattlefieldContext(buff_dict={}, skill_dict={s.id: s for s in SKILLS})
    ctx.add_character(
        get_test_preset(
            USER.name,
            attack_range=attack_range,
            max_cost=10,
            skill_1_id=TARGET_DASH.id,
            skill_2_id=COLUMN_DASH.id,
            skill_3_id=THROW.id,
            skill_4_id=PULL.id,
        ),
        FactionType.ALLY,
        BattlefieldColumnIndex(user_column),
    )
    ctx.characters[USER].status.remaining_cost = 10
    return ctx


def _add(ctx: BattlefieldContext, name: str, faction: FactionType, column: int):
    ctx.add_character(get_test_preset(name), faction, BattlefieldColumnIndex(column))
    return CharacterId(name)


def _cost(ctx: BattlefieldContext, text: str) -> int:
    return try_expansion_if_valid(ctx, parse_character_command(USER, text, ctx))[1]


def test_move_after_target_dash_costs_from_landing_column():
    """돌진 뒤의 이동은 착지 열에서 잰다 — 이동 전 위치에서 재면 1열→4열
    3코스트로 계산된다."""
    ctx = _setup(0)
    _add(ctx, "대상", FactionType.ENEMY, 2)

    assert _cost(ctx, "[TargetDash/대상 - 이동/4열]") == 1 + 1


def test_move_after_column_dash_costs_from_destination():
    ctx = _setup(0)

    assert _cost(ctx, "[ColumnDash/3열 - 이동/4열]") == 1 + 1


def test_move_after_throwing_self_costs_from_thrown_column():
    """자신을 지정한 강제 이동도 시전자의 위치를 바꾼다."""
    ctx = _setup(1)

    assert _cost(ctx, f"[Throw/{USER.name}/3열 - 이동/4열]") == 1 + 1


def test_moves_before_and_after_dash_chain_their_costs():
    ctx = _setup(0)
    _add(ctx, "대상", FactionType.ENEMY, 4)

    # 1열→2열(1) · 2열에서 5열로 돌진(1) · 5열→6열(1)
    assert _cost(ctx, "[이동/2열 - TargetDash/대상 - 이동/6열]") == 3


def test_chained_dash_then_move_is_processed_with_matching_cost():
    """실제 처리에서도 계산한 코스트만큼만 소모되고 목적지에 선다."""
    ctx = _setup(0)
    manager = RoundManager(ctx)
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    ctx.characters[USER].status.remaining_cost = 2
    _add(ctx, "대상", FactionType.ENEMY, 2)

    manager.process_command(
        parse_character_command(USER, "[TargetDash/대상 - 이동/4열]", ctx)
    )

    assert ctx.find_character_position(USER) == BattlefieldColumnIndex(3)
    assert ctx.characters[USER].status.remaining_cost == 0


def test_self_throw_after_move_is_adjacent_to_moved_column():
    """인접 열 판정도 앞 파트의 이동을 반영한 시전자 위치에서 한다."""
    ctx = _setup(0)

    assert _cost(ctx, f"[이동/3열 - Throw/{USER.name}/4열]") == 2 + 1


def test_pull_after_move_pulls_to_moved_column():
    """시전자 위치로 끌어오는 효과는 앞 파트가 옮긴 시전자 위치가 기준이다."""
    ctx = _setup(0)
    manager = RoundManager(ctx)
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    ctx.characters[USER].status.remaining_cost = 10
    pulled = _add(ctx, "대상", FactionType.ALLY, 4)

    manager.process_command(
        parse_character_command(USER, "[이동/3열 - Pull/대상]", ctx)
    )

    assert ctx.find_character_position(pulled) == BattlefieldColumnIndex(2)


def test_attack_after_forced_move_checks_range_at_new_column():
    """앞 파트가 사거리 밖으로 옮긴 대상은 뒤 파트 공격이 닿지 않는다."""
    ctx = _setup(0, attack_range=1)
    _add(ctx, "대상", FactionType.ENEMY, 1)

    with pytest.raises(CommandValidationError):
        _cost(ctx, "[Throw/대상/3열 - 공격/대상]")


def test_attack_after_pulling_target_into_range_is_allowed():
    ctx = _setup(0, attack_range=1)
    _add(ctx, "대상", FactionType.ENEMY, 2)

    assert _cost(ctx, "[Throw/대상/2열 - 공격/대상]") == 1 + 1
