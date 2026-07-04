import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

from bot import commands as _  # noqa: E402, F401
from bot.commands import noncombat as noncombat_module  # noqa: E402
from bot.commands.noncombat import handle_daily_quest_roll  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.noncombat_state import DailyQuestMidState  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet  # noqa: E402


def _make_state(acct: str) -> BotState:
    state = BotState(
        buff_dict={},
        skill_dict={},
        passive_skill_dict={},
        item_dict={},
        inventory=None,
        char_dict={acct: get_test_preset("동료")},
        name_dict={},
        noncombat_char_dict={
            acct: NoncombatCharacterDataFromSpreadsheet(
                name="동료", stat_physical=2, gold=10, daily_quest_date=""
            )
        },
        spreadsheet=None,
    )
    state.noncombat.daily_quest_mid[acct] = DailyQuestMidState(
        quest_id="퀘스트1", bot_reply_post_id=123
    )
    return state


def test_daily_quest_roll_reports_success_and_clears_mid_when_save_succeeds(
    monkeypatch,
):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_gold_and_quest_date", lambda *a, **k: None
    )

    result = handle_daily_quest_roll(acct, "육체", state)

    assert "사례로 1G를 획득했다" in result
    assert acct not in state.noncombat.daily_quest_mid
    assert state.noncombat_char_dict[acct].gold == 11


def test_daily_quest_roll_reports_failure_and_keeps_mid_when_save_fails(monkeypatch):
    acct = "user1"
    state = _make_state(acct)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(
        noncombat_module, "update_character_gold_and_quest_date", _boom
    )

    result = handle_daily_quest_roll(acct, "육체", state)

    assert "사례로 1G를 획득했다" not in result
    assert "저장" in result
    assert acct in state.noncombat.daily_quest_mid
    assert state.noncombat_char_dict[acct].gold == 10
