"""[판정/스탯]에 붙일 목표치는 스레드에서 가장 가까운 world/admin 게시물이 정한다."""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from bot.main import BotState, MastodonBotListener  # noqa: E402
from test_bot_admin import _FakeMastodon  # noqa: E402


def _make_state() -> BotState:
    return BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )


def _post(acct: str, text: str) -> dict:
    return {"account": {"acct": acct}, "content": f"<p>{text}</p>"}


def _find_roll_target(ancestors: list[dict]):
    listener = MastodonBotListener(
        _FakeMastodon(ancestors=ancestors), _make_state(), bot_acct="bot"
    )
    return listener._find_roll_target(900, 899)


def test_find_roll_target_walks_up_past_player_replies():
    """플레이어들이 서로의 판정에 이어 달아도 world 게시물까지 거슬러 올라간다."""
    target = _find_roll_target(
        [
            _post("test-world", "<strong>[판정: 최소 1인] [지식 8]</strong>"),
            _post("user2", "[판정/지식]"),
            _post("bot", "◊ 판정: 2[지식] + 6[1d6] → 「8」"),
        ]
    )

    assert target is not None
    assert target.thresholds == {"지식": 8}


def test_find_roll_target_uses_nearest_world_post_only():
    """재시도 요구가 원래 요구를 대신하고, 목표치 없는 서술이 끼면 판정이 끝난 것이다."""
    retried = _find_roll_target(
        [
            _post("test-world", "[판정: 최소 1인] [마법 7]"),
            _post("test-world", "[판정: 최소 1인] [마법 7, 실패 시 패널티]"),
        ]
    )
    narrated = _find_roll_target(
        [
            _post("test-world", "[판정: 최소 1인] [마법 7]"),
            _post("test-world", "성공. 이제 어떻게 할까?"),
        ]
    )

    assert retried is not None and retried.penalty
    assert narrated is None


def test_find_roll_target_ignores_non_world_posts():
    assert _find_roll_target([_post("user2", "[판정: 최소 1인] [지식 8]")]) is None


def test_find_roll_target_reads_admin_post():
    target = _find_roll_target([_post("test-admin", "[판정: 최소 1인] [육체 7]")])

    assert target is not None
    assert target.thresholds == {"육체": 7}
