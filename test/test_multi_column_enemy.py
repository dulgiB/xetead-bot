"""여러 열에 걸친 에너미(`span`) 동작 검증.

배치 위치는 언제나 가장 왼쪽 열이고, 사거리 판정은 양쪽 모두 점유 열 전체를
본다 — 아군은 점유 열 중 하나라도 사거리 안이면 때릴 수 있고, 에너미는 양 끝
열 어디서든 범위를 잡는다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import try_expansion_if_valid
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    ActionType,
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


def _place_wide_enemy(context, column: int, *, span: int = 3, attack_range: int = 1):
    context.add_character(
        get_test_preset("거대적", span=span, attack_range=attack_range),
        FactionType.ENEMY,
        BattlefieldColumnIndex(column),
    )
    return CharacterId("거대적")


def test_occupies_every_column_in_span(empty_context):
    """span만큼의 열 전부에 같은 슬롯으로 등록되고, 위치는 가장 왼쪽 열이다."""
    enemy_id = _place_wide_enemy(empty_context, 2)

    assert empty_context.find_character_position(enemy_id) == BattlefieldColumnIndex(2)
    assert empty_context.find_character_columns(enemy_id) == (
        BattlefieldColumnIndex(2),
        BattlefieldColumnIndex(3),
        BattlefieldColumnIndex(4),
    )
    for column in (2, 3, 4):
        slots = empty_context.position_map[FactionType.ENEMY][
            BattlefieldColumnIndex(column)
        ]
        assert list(slots.values()) == [enemy_id]
        assert list(slots.keys()) == [0]
    assert (
        empty_context.position_map[FactionType.ENEMY][BattlefieldColumnIndex(5)] == {}
    )


def test_removal_clears_every_column(empty_context):
    """제거하면 걸쳐 있던 열 전부에서 빠져 유령 슬롯이 남지 않는다."""
    enemy_id = _place_wide_enemy(empty_context, 0)
    empty_context.remove_character(enemy_id)

    assert all(
        not slots for slots in empty_context.position_map[FactionType.ENEMY].values()
    )


def test_span_out_of_board_rejected(empty_context):
    """오른쪽 끝이 전장을 벗어나는 배치는 거부된다 (기준은 가장 왼쪽 열)."""
    with pytest.raises(CommandValidationError):
        _place_wide_enemy(empty_context, 5, span=3)

    # 딱 맞게 들어가는 위치는 허용된다.
    _place_wide_enemy(empty_context, 4, span=3)


def test_span_consumes_slot_in_every_column(empty_context):
    """걸친 열마다 슬롯 하나씩을 차지하므로 그 열들의 정원이 함께 줄어든다."""
    _place_wide_enemy(empty_context, 0, span=2)

    for i in range(CHARACTER_PER_COLUMN - 1):
        empty_context.add_character(
            get_test_preset(f"적{i}"), FactionType.ENEMY, BattlefieldColumnIndex(1)
        )
    with pytest.raises(CommandValidationError):
        empty_context.add_character(
            get_test_preset("초과"), FactionType.ENEMY, BattlefieldColumnIndex(1)
        )


def test_ally_can_attack_if_any_occupied_column_in_range(empty_context):
    """아군 사거리에 점유 열 중 하나만 걸쳐도 공격할 수 있다."""
    RoundManager(empty_context)
    _place_wide_enemy(empty_context, 3, span=3)  # 3,4,5열
    empty_context.add_character(
        get_test_preset("아군", attack_range=1),
        FactionType.ALLY,
        BattlefieldColumnIndex(2),
    )

    # 아군은 2열, 사거리 1 → 1~3열. 적의 왼쪽 끝(3열)만 닿는다.
    command = parse_character_command(
        CharacterId("아군"), "[공격/거대적]", empty_context
    )
    parts, _ = try_expansion_if_valid(empty_context, command)
    assert parts


def test_ally_out_of_range_of_every_occupied_column_is_rejected(empty_context):
    """점유 열 어디에도 닿지 않으면 거부된다."""
    RoundManager(empty_context)
    _place_wide_enemy(empty_context, 4, span=2)  # 4,5열
    empty_context.add_character(
        get_test_preset("아군", attack_range=1),
        FactionType.ALLY,
        BattlefieldColumnIndex(2),
    )

    command = parse_character_command(
        CharacterId("아군"), "[공격/거대적]", empty_context
    )
    with pytest.raises(CommandValidationError):
        try_expansion_if_valid(empty_context, command)


def test_enemy_measures_range_from_both_ends(empty_context):
    """에너미는 양 끝 열을 기준으로 공격 범위를 잡는다."""
    RoundManager(empty_context)
    enemy_id = _place_wide_enemy(empty_context, 2, span=3, attack_range=1)  # 2,3,4열
    # 오른쪽 끝(4열) + 사거리 1 = 5열까지 닿는다.
    empty_context.add_character(
        get_test_preset("우측아군"), FactionType.ALLY, BattlefieldColumnIndex(5)
    )
    # 왼쪽 끝(2열) - 사거리 1 = 1열까지 닿는다.
    empty_context.add_character(
        get_test_preset("좌측아군"), FactionType.ALLY, BattlefieldColumnIndex(1)
    )
    # 6열은 오른쪽 끝에서도 2칸이라 닿지 않는다.
    empty_context.add_character(
        get_test_preset("먼아군"), FactionType.ALLY, BattlefieldColumnIndex(6)
    )

    for target in ("우측아군", "좌측아군"):
        command = parse_character_command(enemy_id, f"[공격/{target}]", empty_context)
        assert try_expansion_if_valid(empty_context, command)[0]

    command = parse_character_command(enemy_id, "[공격/먼아군]", empty_context)
    with pytest.raises(CommandValidationError):
        try_expansion_if_valid(empty_context, command)


def test_shares_column_uses_overlap(empty_context):
    """ "같은 열" 판정도 한 열이라도 겹치면 참이다."""
    enemy_id = _place_wide_enemy(empty_context, 2, span=3)
    empty_context.add_character(
        get_test_preset("동료"), FactionType.ENEMY, BattlefieldColumnIndex(4)
    )
    empty_context.add_character(
        get_test_preset("딴열"), FactionType.ENEMY, BattlefieldColumnIndex(5)
    )

    assert empty_context.shares_column(enemy_id, CharacterId("동료"))
    assert not empty_context.shares_column(enemy_id, CharacterId("딴열"))


def test_move_keeps_span_and_allows_overlapping_step(empty_context):
    """점유 열이 겹치는 한 칸 이동도 자기 자신 때문에 막히지 않는다."""
    enemy_id = _place_wide_enemy(empty_context, 2, span=3)
    empty_context.move_character_to(enemy_id, BattlefieldColumnIndex(3))

    assert empty_context.find_character_columns(enemy_id) == (
        BattlefieldColumnIndex(3),
        BattlefieldColumnIndex(4),
        BattlefieldColumnIndex(5),
    )
    assert (
        empty_context.position_map[FactionType.ENEMY][BattlefieldColumnIndex(2)] == {}
    )


def test_move_past_board_edge_rejected(empty_context):
    """이동으로도 오른쪽 끝이 전장을 벗어날 수 없다."""
    enemy_id = _place_wide_enemy(empty_context, 2, span=3)
    with pytest.raises(CommandValidationError):
        empty_context.move_character_to(enemy_id, BattlefieldColumnIndex(5))


def test_column_aoe_hits_once_per_covered_column():
    """열 광역기는 덮은 열 수만큼 다열 에너미를 중복해서 때린다 — 걸친 열
    전부에 등록돼 있으므로 열 단위 대상 수집이 그만큼 잡는다."""
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleColumnRange",
        target_count=1,  # 지정 열 ±1 = 3열
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={skill.id: skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    ctx.add_character(
        get_test_preset("아군", skill_1_id=skill.id, attack_range=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(3),
    )
    enemy_id = _place_wide_enemy(ctx, 2, span=2)  # 2,3열
    max_hp = ctx.characters[enemy_id].status[CombatStatType.MAX_HP]

    manager.process_command(
        parse_character_command(CharacterId("아군"), "[스킬_1/3]", ctx)
    )

    # 2열과 3열 양쪽에서 한 번씩, 총 2회분(5 x 2)이 들어간다.
    assert ctx.characters[enemy_id].status.curr_hp == max_hp - 10
