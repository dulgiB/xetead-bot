"""대련/결투/상시전투가 커맨드마다 "필드" 행을 갱신하는지 확인한다.

이 스냅샷이 갱신되지 않으면 봇 재기동 복원이 전투 시작 시점으로 되돌아간다 —
체력도 잔여 코스트도 라운드도 전부 첫 라운드 값으로 남기 때문이다. 결투가
실제로 이 상태였다(갱신 대상 종류를 매핑과 따로 나열해 두어 결투만 빠졌다).
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import PracticeBattleMode  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot import log_sheets  # noqa: E402
from bot import main as main_module  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402


def test_every_practice_mode_updates_its_field_row():
    """갱신 대상 종류는 모드 매핑에서 파생돼야 한다 — 따로 나열하면 모드를
    늘렸을 때 거기만 빠뜨린다."""
    assert main_module._PRACTICE_FIELD_TYPES == set(
        main_module._PRACTICE_MODE_TO_FIELD_TYPE.values()
    )
    assert len(main_module._PRACTICE_MODE_TO_FIELD_TYPE) == len(PracticeBattleMode)


def _state_with_practice(mode: PracticeBattleMode) -> tuple[BotState, str]:
    context = PracticeBattlefieldContext(buff_dict={}, skill_dict={}, mode=mode)
    ps = PracticeBattleState(
        context=context,
        manager=PracticeRoundManager(context),
        mode=mode,
        round_n=2,
        field_id="field-1",
        active_post_id=777,
    )
    state = BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    state.practices[777] = ps
    return state, ps.field_id


def _run_persist(monkeypatch, mode: PracticeBattleMode) -> list[dict]:
    state, field_id = _state_with_practice(mode)
    upserts: list[dict] = []
    monkeypatch.setattr(log_sheets, "append_battle_log", lambda *a, **k: None)
    monkeypatch.setattr(
        log_sheets, "upsert_field_row", lambda *a, **k: upserts.append(k)
    )
    main_module._persist_battle_log(
        state,
        log_sheets.BattleCommandLog(
            field_id=field_id,
            round_n=2,
            phase="선공 행동",
            battle_type=main_module._practice_battle_type(state.practices[777]),
            command_text="[이동/2]",
            mastodon_id="acct_a",
        ),
        reply_ref="1",
    )
    return upserts


def test_duel_command_updates_field_row(monkeypatch):
    upserts = _run_persist(monkeypatch, PracticeBattleMode.DUEL)

    assert len(upserts) == 1
    assert upserts[0]["battle_type"] == log_sheets.FieldBattleType.DUEL
    assert upserts[0]["round_n"] == 2


def test_practice_command_updates_field_row(monkeypatch):
    upserts = _run_persist(monkeypatch, PracticeBattleMode.PRACTICE)

    assert len(upserts) == 1
    assert upserts[0]["battle_type"] == log_sheets.FieldBattleType.PRACTICE
