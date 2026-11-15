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

COLUMN_HIT = SkillData(
    id="ColumnHit",
    target_rule="SkillTargetRuleColumn",
    target_count=1,
    cost=1,
    effects=[
        SkillEffectDamage(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None)
    ],
    description="",
)

SKILLS = (TARGET_DASH, COLUMN_DASH, THROW, PULL, COLUMN_HIT)


def _setup(
    user_column: int,
    attack_range: int = 3,
    faction: FactionType = FactionType.ALLY,
) -> BattlefieldContext:
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
            skill_5_id=COLUMN_HIT.id,
        ),
        faction,
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


def _hp(ctx: BattlefieldContext, name: str) -> int:
    return ctx.characters[CharacterId(name)].status.curr_hp


def _process(ctx: BattlefieldContext, text: str) -> RoundManager:
    manager = RoundManager(ctx)
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    ctx.characters[USER].status.remaining_cost = 10
    manager.process_command(parse_character_command(USER, text, ctx))
    return manager


def test_dash_after_forced_move_lands_on_moved_column():
    """앞 파트가 옮긴 대상에게 돌진하면 옮겨진 열로 들어가고, 경로도 그
    열까지다. 옮겨진 대상은 원래 열에서 경로 대미지를 받지 않는다."""
    ctx = _setup(0)
    moved = _add(ctx, "대상", FactionType.ENEMY, 1)
    _add(ctx, "경로", FactionType.ENEMY, 1)

    _process(ctx, "[Throw/대상/3열 - TargetDash/대상]")

    assert ctx.find_character_position(moved) == BattlefieldColumnIndex(2)
    assert ctx.find_character_position(USER) == BattlefieldColumnIndex(2)
    assert _hp(ctx, "대상") == 90
    assert _hp(ctx, "경로") == 95


def test_dash_range_is_checked_to_the_moved_column():
    """사거리 밖의 대상도 앞 파트가 사거리 안으로 옮겼으면 돌진할 수 있고,
    사거리 밖으로 옮겼으면 돌진할 수 없다."""
    ctx = _setup(0, attack_range=1)
    _add(ctx, "끌려올 대상", FactionType.ENEMY, 2)
    _add(ctx, "밀려날 대상", FactionType.ENEMY, 1)

    assert _cost(ctx, "[Throw/끌려올 대상/2열 - TargetDash/끌려올 대상]") == 2
    with pytest.raises(CommandValidationError):
        _cost(ctx, "[Throw/밀려날 대상/3열 - TargetDash/밀려날 대상]")


def test_move_after_forced_move_and_dash_costs_from_moved_column():
    ctx = _setup(0)
    _add(ctx, "대상", FactionType.ENEMY, 1)

    # 대상을 3열로 옮김(1) · 3열로 돌진(1) · 3열→4열(1)
    assert _cost(ctx, "[Throw/대상/3열 - TargetDash/대상 - 이동/4열]") == 3


def test_column_dash_after_forced_move_hits_the_moved_target():
    ctx = _setup(0)
    _add(ctx, "들어온 대상", FactionType.ENEMY, 3)
    _add(ctx, "나간 대상", FactionType.ENEMY, 2)

    _process(
        ctx,
        "[Throw/들어온 대상/3열 - Throw/나간 대상/4열 - ColumnDash/3열]",
    )

    assert _hp(ctx, "들어온 대상") == 95
    assert _hp(ctx, "나간 대상") == 100


def test_column_skill_after_forced_move_hits_the_moved_column():
    ctx = _setup(0)
    _add(ctx, "대상", FactionType.ENEMY, 1)

    _process(ctx, "[Throw/대상/3열 - ColumnHit/3열]")

    assert _hp(ctx, "대상") == 90


def test_enemy_forced_move_then_dash_is_not_pushed_twice_at_resolution():
    """에너미는 선언 때 이동하고 정산 때 재전개한다. 재전개는 이미 옮겨진
    위치에서 다시 펼치므로 같은 강제 이동을 한 번 더 반영하면 안 된다."""
    ctx = _setup(0, faction=FactionType.ENEMY)
    manager = RoundManager(ctx)
    ctx.characters[USER].status.remaining_cost = 10
    moved = _add(ctx, "대상", FactionType.ALLY, 1)
    _add(ctx, "경로", FactionType.ALLY, 1)

    manager.process_command(
        parse_character_command(USER, "[Throw/대상/3열 - TargetDash/대상]", ctx)
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.find_character_position(moved) == BattlefieldColumnIndex(2)
    assert ctx.find_character_position(USER) == BattlefieldColumnIndex(2)
    assert _hp(ctx, "대상") == 90
    assert _hp(ctx, "경로") == 95


def test_enemy_move_to_adjacent_column_skill_resolves_without_error():
    """에너미가 대상을 인접 열로 옮기는 스킬을 쓰면 정산 재전개 때 대상은 이미
    그 열에 있다. 인접 판정을 다시 하면 "점유 열 지정"으로 보여 정산이 멈췄다."""
    ctx = _setup(0, faction=FactionType.ENEMY)
    manager = RoundManager(ctx)
    ctx.characters[USER].status.remaining_cost = 10
    moved = _add(ctx, "대상", FactionType.ALLY, 1)

    manager.process_command(parse_character_command(USER, "[Throw/대상/3열]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.find_character_position(moved) == BattlefieldColumnIndex(2)
