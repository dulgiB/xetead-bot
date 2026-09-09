"""체력이 0 이하인 캐릭터의 커맨드 선언 차단 테스트.

아군은 체력이 0이 되어도 부활 여지 때문에 필드에서 자동 제거되지 않으므로
(`BattlefieldContext._remove_eliminated_characters()`), 이 검증이 없으면
전투불능 상태에서 커맨드가 그대로 통과한다. 막는 것은 **행동 주체**뿐이고,
대상으로 지정되어 계속 피격되는 기존 설계는 그대로 유지되어야 한다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import (
    process_ally_command,
    process_enemy_command_on_pre_action,
    try_expansion_if_valid,
)
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from helpers import get_test_preset

_ACTOR = CharacterId("Catastrophe")
_TARGET = CharacterId("Adversary")


def _make_context(actor_faction: FactionType = FactionType.ALLY) -> BattlefieldContext:
    context = BattlefieldContext(buff_dict={}, skill_dict={})
    context.add_character(
        get_test_preset(_ACTOR.name), actor_faction, BattlefieldColumnIndex(3)
    )
    context.add_character(
        get_test_preset(_TARGET.name), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )
    return context


def _run(context: BattlefieldContext, text: str):
    command = parse_character_command(_ACTOR, text, context)
    assert command is not None
    return process_ally_command(context, command)


def test_defeated_character_cannot_attack():
    """체력이 정확히 0이어도 커맨드를 낼 수 없다."""
    context = _make_context()
    context.characters[_ACTOR].status.curr_hp = 0
    with pytest.raises(CommandValidationError, match="행동할 수 없습니다"):
        _run(context, f"[공격/{_TARGET.name}]")


def test_defeated_character_cannot_move_either():
    """공격뿐 아니라 이동 등 모든 커맨드가 막혀야 한다."""
    context = _make_context()
    context.characters[_ACTOR].status.curr_hp = -5
    with pytest.raises(CommandValidationError, match="행동할 수 없습니다"):
        _run(context, "[이동/5]")


def test_enemy_pre_declaration_is_blocked_too():
    """진영 무관으로 적용한다 — 적군의 PRE 선언도 체력 0이면 막힌다."""
    context = _make_context(actor_faction=FactionType.ENEMY)
    context.characters[_ACTOR].status.curr_hp = 0

    command = parse_character_command(_ACTOR, f"[공격/{_TARGET.name}]", context)
    assert command is not None
    with pytest.raises(CommandValidationError, match="행동할 수 없습니다"):
        process_enemy_command_on_pre_action(context, command, {})


def test_defeated_character_can_still_be_targeted():
    """행동 주체만 막고, 대상으로 지정되는 것은 기존대로 허용한다."""
    context = _make_context()
    context.characters[_TARGET].status.curr_hp = 0

    command = parse_character_command(_ACTOR, f"[공격/{_TARGET.name}]", context)
    assert command is not None
    # 검증 단계에서 예외가 나지 않아야 한다.
    try_expansion_if_valid(context, command)


def test_healthy_character_is_unaffected():
    """체력이 남아 있으면 기존과 동일하게 통과한다."""
    context = _make_context()
    _run(context, f"[공격/{_TARGET.name}]")
    assert context.characters[_TARGET].status.curr_hp < 100
