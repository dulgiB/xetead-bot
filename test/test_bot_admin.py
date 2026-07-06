import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import itertools

from battle.objects.define import BattlefieldColumnIndex, FactionType  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import SideType  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot.commands import admin as admin_module  # noqa: E402
from bot.commands.admin import _cmd_battle_start  # noqa: E402
from bot.main import BotState, MastodonBotListener  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402


def _make_state(**pending) -> BotState:
    state = BotState(
        buff_dict={},
        skill_dict={},
        passive_skill_dict={},
        item_dict={},
        inventory=None,
        char_dict={},
        name_dict={"유효 캐릭터": get_test_preset("유효 캐릭터")},
        noncombat_char_dict={},
        spreadsheet=None,
    )
    state.session = BattleSession(buff_dict={}, skill_dict={})
    state.pending_placements = pending.get("pending_placements", [])
    state.pending_participants = pending.get("pending_participants", [])
    return state


def test_battle_does_not_start_when_all_placements_fail():
    """모든 배치가 실패(존재하지 않는 캐릭터 등)하면 전투가 시작되면 안 된다."""
    state = _make_state(
        pending_placements=[
            ("존재하지 않는 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )

    result = _cmd_battle_start(state)

    assert state.session.started is False
    assert len(state.session.context.characters) == 0
    assert "시작하지 못했습니다" in result.reply_text


def test_battle_starts_when_at_least_one_placement_succeeds():
    """일부 배치만 성공해도(캐릭터 1명 이상) 전투는 정상적으로 시작되어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
            ("존재하지 않는 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(1)),
        ]
    )

    result = _cmd_battle_start(state)

    assert state.session.started is True
    assert len(state.session.context.characters) == 1
    assert "전투 시작" in result.reply_text


def test_investigation_battle_inline_placement_respects_faction_token(monkeypatch):
    """[상시전투]와 함께 입력된 [배치/이름/아군 3열]은 '아군' 토큰대로
    SIDE_1(아군)에 배치되어야 하며, 무조건 적(SIDE_2)으로 배치되면 안 된다."""
    state = _make_state()
    state.name_dict = {"동료": get_test_preset("동료")}
    monkeypatch.setattr(
        admin_module,
        "load_char_data",
        lambda spreadsheet: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )

    result = admin_module._cmd_investigation_battle(
        "[상시전투][배치/동료/아군 3열]", [], state
    )

    assert not result.reply_text or "오류" not in (result.game_post_text or "")
    char_id = CharacterId("동료")
    assert char_id in state.practice.context.characters
    assert state.practice.context.get_side(char_id) == SideType.SIDE_1


class _FakeMastodon:
    def __init__(self):
        self._next_id = itertools.count(9000)

    def status_post(self, *args, **kwargs):
        return {"id": next(self._next_id)}


def _make_notification(acct: str, status_id: int, in_reply_to_id: int, text: str) -> dict:
    return {
        "type": "mention",
        "account": {"acct": acct},
        "status": {
            "id": status_id,
            "content": f"<p>@bot {text}</p>",
            "visibility": "public",
            "in_reply_to_id": in_reply_to_id,
            "mentions": [{"acct": "bot"}],
        },
    }


def test_replying_again_to_stale_prep_post_does_not_restart_battle():
    """포지션 선언이 완료되어 전투가 시작된 뒤, 같은 참가자가 실수로 원본
    준비 게시물에 다시 답글을 달아도 전투가 재시작되면 안 된다."""
    state = _make_state()
    state.char_dict = {"user1": get_test_preset("동료")}

    context = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    manager = PracticeRoundManager(context)
    state.practice = PracticeBattleState(
        context=context,
        manager=manager,
        is_investigation=True,
        expected_accts=["user1"],
        prep_post_id=1000,
    )

    listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

    listener.on_notification(
        _make_notification("user1", 1, 1000, "[아군/1열]")
    )

    assert state.practice.prep_post_id == 0
    assert len(state.practice.context.characters) == 1
    round_n_after_start = state.practice.round_n

    # 같은 참가자가 이미 소모된 원본 준비 게시물(1000)에 다시 답글
    listener.on_notification(
        _make_notification("user1", 2, 1000, "[아군/2열]")
    )

    assert len(state.practice.context.characters) == 1
    assert state.practice.round_n == round_n_after_start


def test_malformed_notification_does_not_raise():
    """형식이 예상과 다른(status가 없는 등) 알림이 와도 예외가 밖으로
    전파되면 안 된다 — 스트리밍 리스너 전체가 죽는 것을 방지한다."""
    state = _make_state()
    listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

    listener.on_notification({"type": "mention", "account": {"acct": "user1"}})
