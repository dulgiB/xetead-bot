"""대련/상시전투의 한 페이즈는 그 팀 전원이 선언해야 넘어간다.

커맨드 하나만 처리하고 곧바로 페이즈를 넘기면 팀에 몇 명이 있든 라운드당 한
명만 행동할 수 있다 — 나머지의 답글은 active_post_id가 이미 옮겨간 뒤라
어느 분기에도 걸리지 않고 에러 없이 무시된다.
"""

import pytest
from battle.core.commands.parser import parse_character_command
from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import CharacterId
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager
from helpers import get_test_preset

from battle.exceptions import CommandValidationError


def _make_context() -> PracticeBattlefieldContext:
    return PracticeBattlefieldContext(buff_dict={}, skill_dict={})


def _place(ctx, name: str, side: SideType, column: int = 0, **preset_kwargs) -> None:
    ctx.add_character(
        get_test_preset(name, **preset_kwargs), side, BattlefieldColumnIndex(column)
    )


def _force_movers(manager, first: SideType) -> None:
    """선공/후공을 테스트가 원하는 쪽으로 고정한다 (첫 라운드는 무작위 추첨)."""
    manager._first_mover, manager._second_mover = first, first.opposite


def test_every_member_of_the_acting_side_can_declare_once():
    """한 페이즈에서 그 팀의 캐릭터는 각자 한 번씩 선언할 수 있고, 전원이
    선언을 마치기 전까지 pending_actors()가 비지 않는다."""
    ctx = _make_context()
    _place(ctx, "A", SideType.SIDE_1)
    _place(ctx, "A2", SideType.SIDE_1)
    _place(ctx, "B", SideType.SIDE_2)
    manager = PracticeRoundManager(ctx)
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    _force_movers(manager, SideType.SIDE_1)

    assert {c.name for c in manager.pending_actors()} == {"A", "A2"}

    manager.process_command(parse_character_command(CharacterId("A"), "[이동/2]", ctx))
    assert {c.name for c in manager.pending_actors()} == {"A2"}

    manager.process_command(parse_character_command(CharacterId("A2"), "[이동/2]", ctx))
    assert manager.pending_actors() == []


def test_same_character_cannot_declare_twice_in_one_phase():
    ctx = _make_context()
    _place(ctx, "A", SideType.SIDE_1)
    _place(ctx, "A2", SideType.SIDE_1)
    _place(ctx, "B", SideType.SIDE_2)
    manager = PracticeRoundManager(ctx)
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    _force_movers(manager, SideType.SIDE_1)

    manager.process_command(parse_character_command(CharacterId("A"), "[이동/2]", ctx))
    with pytest.raises(CommandValidationError, match="이미"):
        manager.process_command(
            parse_character_command(CharacterId("A"), "[이동/3]", ctx)
        )


def test_defeated_and_companion_characters_are_not_awaited():
    """체력 0인 캐릭터(커맨드 자체가 막힌다)와 동료(플레이어가 조작하지
    않는다)를 기다리면 아무도 채울 수 없는 대기 조건이 된다."""
    ctx = _make_context()
    _place(ctx, "A", SideType.SIDE_1)
    _place(ctx, "A2", SideType.SIDE_1)
    _place(ctx, "B", SideType.SIDE_2)
    ctx.characters[CharacterId("A2")].status.curr_hp = 0
    # 동료는 position_map 슬롯을 차지하지 않고 companion_owners로만 등록된다.
    ctx._spawn_companion_character(
        ctx.characters[CharacterId("A")], CharacterId("P"), 20
    )

    manager = PracticeRoundManager(ctx)
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    _force_movers(manager, SideType.SIDE_1)

    assert [c.name for c in manager.pending_actors()] == ["A"]


def test_phase_transition_resets_declarations():
    ctx = _make_context()
    _place(ctx, "A", SideType.SIDE_1)
    _place(ctx, "B", SideType.SIDE_2)
    manager = PracticeRoundManager(ctx)
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    _force_movers(manager, SideType.SIDE_1)

    manager.process_command(parse_character_command(CharacterId("A"), "[이동/2]", ctx))
    manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)

    assert manager.declared_this_phase == set()
    assert [c.name for c in manager.pending_actors()] == ["B"]
