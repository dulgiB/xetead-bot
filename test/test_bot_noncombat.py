import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

from bot import commands as _  # noqa: E402, F401
from bot.commands import noncombat as noncombat_module  # noqa: E402
from bot.commands.noncombat import (  # noqa: E402
    handle_daily_quest_roll,
    handle_investigation_venue_choice,
)
from bot.main import BotState  # noqa: E402
from bot.noncombat_state import DailyQuestMidState  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet  # noqa: E402
from spreadsheets.models.quest import QuestData  # noqa: E402


def _make_state(acct: str) -> BotState:
    state = BotState(
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


def test_failed_venue_choice_clears_stale_quest_mapping(monkeypatch):
    """유효한 장소를 골라 의뢰를 확인한 뒤, 같은 메뉴에 다시 무효한 장소를
    입력하면 이전에 저장된 quest_id가 남아 있으면 안 된다 (엉뚱한 의뢰의
    수주로 이어지는 것을 방지)."""
    acct = "user1"
    state = _make_state(acct)
    state.noncombat.investigation_venue_to_quest = {"장소A": "q1"}
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quests",
        lambda spreadsheet: [
            QuestData(
                id="q1",
                name="퀘스트1",
                description="설명",
                type="탐사",
                subtype="상시",
                location="",
                venue_name="장소A",
                reward="10G",
                available_until="",
            )
        ],
    )

    # 1. 유효한 장소를 선택 → quest_id가 저장된다
    handle_investigation_venue_choice(acct, "장소A", state)
    assert state.noncombat.investigation_acct_to_quest_id.get(acct) == "q1"

    # 2. 같은 메뉴에 존재하지 않는 장소를 다시 입력 → 실패 응답이지만
    #    이전에 저장된 quest_id는 지워져야 한다
    result = handle_investigation_venue_choice(acct, "존재하지 않는 장소", state)

    assert "이번 조사의 장소가 아닙니다" in result
    assert acct not in state.noncombat.investigation_acct_to_quest_id
