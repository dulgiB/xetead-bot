"""상시전투의 실제 체력 규칙 테스트.

상시전투는 대련과 진행이 같지만(world 프록시로 적 입력, 아군 선공 고정)
체력만 다르다:
  1. 양 진영 모두 임시 체력 없이 "캐릭터"/"에너미" 시트의 실제 체력으로 싸운다.
  2. 체력 변동은 커맨드가 처리될 때마다 시트에 반영된다.
그리고 결투처럼 라운드 상한이 없고, 실제 체력으로 싸우므로 키워드 보정을
쓸 수 있다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.objects.define import (  # noqa: E402
    KEYWORD_BOOST_HP_COST,
    BattlefieldColumnIndex,
    CombatStatType,
)
from battle.objects.models import CharacterId  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import PracticeBattleMode, SideType  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot import main as main_module  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from test_practice_duel_mode import _FakeSpreadsheet  # noqa: E402

_ALLY = CharacterId("Catastrophe")
_ENEMY = CharacterId("Adversary")


def _investigation_context() -> PracticeBattlefieldContext:
    return PracticeBattlefieldContext(
        buff_dict={}, skill_dict={}, mode=PracticeBattleMode.INVESTIGATION
    )


def test_ally_uses_sheet_hp_as_is():
    ctx = _investigation_context()
    ctx.add_character(
        get_test_preset(_ALLY.name, max_hp=100, initial_hp=70),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )

    ally = ctx.characters[_ALLY]
    assert ally.status.curr_hp == 70
    assert ally.status[CombatStatType.MAX_HP] == 100


def test_enemy_uses_sheet_hp_as_is():
    ctx = _investigation_context()
    ctx.add_character(
        get_test_preset(_ENEMY.name, max_hp=100, initial_hp=40),
        SideType.SIDE_2,
        BattlefieldColumnIndex(0),
    )

    enemy = ctx.characters[_ENEMY]
    assert enemy.status.curr_hp == 40
    assert enemy.status[CombatStatType.MAX_HP] == 100


def _investigation_state(
    monkeypatch, *, ally_hp: int, enemy_hp: int = 100, revival_count: int = 0
) -> tuple[PracticeBattleState, BotState]:
    monkeypatch.setattr(main_module, "_upsert_practice_field_row", lambda *a, **k: None)
    ctx = _investigation_context()
    ctx.add_character(
        get_test_preset(_ENEMY.name, max_hp=100, initial_hp=enemy_hp, atk=10),
        SideType.SIDE_2,
        BattlefieldColumnIndex(3),
    )
    ally = get_test_preset(
        _ALLY.name, max_hp=100, initial_hp=ally_hp, revival_count=revival_count
    )
    ps = PracticeBattleState(
        context=ctx,
        manager=PracticeRoundManager(ctx),
        mode=PracticeBattleMode.INVESTIGATION,
        active_post_id=1,
        declared={"acct_a": (SideType.SIDE_1, BattlefieldColumnIndex(3))},
    )
    state = BotState(
        char_dict={"acct_a": ally},
        name_dict={_ALLY.name: ally, _ENEMY.name: get_test_preset(_ENEMY.name)},
        noncombat_char_dict={},
        spreadsheet=_FakeSpreadsheet({_ALLY.name: ally_hp, _ENEMY.name: enemy_hp}),
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    main_module._start_investigation_battle(state, ps)
    state.practices[1] = ps
    return ps, state


def test_hp_changes_of_both_sides_are_written_to_sheet(monkeypatch):
    ps, state = _investigation_state(monkeypatch, ally_hp=70)

    main_module._handle_practice_command("acct_a", f"[공격/{_ENEMY.name}]", state, ps)
    main_module._handle_practice_proxy_command(
        f"{_ENEMY.name} [공격/{_ALLY.name}]", state, "test-world", session=ps
    )

    ally_hp = ps.context.characters[_ALLY].status.curr_hp
    enemy_hp = ps.context.characters[_ENEMY].status.curr_hp
    assert ally_hp < 70
    assert enemy_hp < 100
    assert state.spreadsheet.hp_of(_ALLY.name) == ally_hp
    assert state.spreadsheet.hp_of(_ENEMY.name) == enemy_hp


def test_enemy_eliminated_at_round_end_is_written_as_zero(monkeypatch):
    """라운드 종료 DoT로 쓰러진 적은 그 자리에서 필드에서 빠진다 — 빠진
    뒤에도 쓰러진 체력(0)이 시트에 남아야 한다."""
    ps, state = _investigation_state(monkeypatch, ally_hp=70, enemy_hp=30)
    main_module._write_back_sheet_hp(state, ps)
    ps.context.characters[_ENEMY].status.curr_hp = 0

    ps.end_round()
    assert _ENEMY not in ps.context.characters
    main_module._write_back_sheet_hp(state, ps)

    assert state.spreadsheet.hp_of(_ENEMY.name) == 0


def test_unchanged_hp_is_not_rewritten(monkeypatch):
    """바뀐 캐릭터만 쓴다 — 시트 쓰기 할당량을 커맨드마다 인원수만큼 쓰지 않도록."""
    ps, state = _investigation_state(monkeypatch, ally_hp=70)
    main_module._write_back_sheet_hp(state, ps)
    worksheet = state.spreadsheet.worksheet("캐릭터")
    worksheet.written.clear()

    main_module._write_back_sheet_hp(state, ps)

    assert worksheet.written == []


def test_failed_write_is_retried_next_time(monkeypatch):
    ps, state = _investigation_state(monkeypatch, ally_hp=70)
    ps.context.characters[_ALLY].status.curr_hp = 40
    monkeypatch.setattr(
        main_module.log_sheets, "write_back_character_hp", lambda *a, **k: set()
    )
    main_module._write_back_sheet_hp(state, ps)
    monkeypatch.undo()

    main_module._write_back_sheet_hp(state, ps)

    assert state.spreadsheet.hp_of(_ALLY.name) == 40


def test_investigation_has_no_round_limit(monkeypatch):
    """한쪽이 전멸할 때까지 계속된다."""
    ps, _state = _investigation_state(monkeypatch, ally_hp=70)

    assert ps.round_limit is None


def test_keyword_boost_cost_comes_out_of_sheet_hp(monkeypatch):
    """상시전투의 키워드 보정 대가는 전장 체력(=실제 체력)에서 빠지고 시트에
    반영되며, 오늘 사용한 것으로 기록된다."""
    ps, state = _investigation_state(monkeypatch, ally_hp=70, revival_count=1)
    marked = []
    monkeypatch.setattr(
        main_module,
        "mark_keyword_used_if_needed",
        lambda state, char_id, command: marked.append(char_id),
    )

    main_module._handle_practice_command("acct_a", f"[공격+/{_ENEMY.name}]", state, ps)

    ally_hp = ps.context.characters[_ALLY].status.curr_hp
    assert ally_hp == 70 - KEYWORD_BOOST_HP_COST
    assert state.spreadsheet.hp_of(_ALLY.name) == ally_hp
    assert marked == [_ALLY]
