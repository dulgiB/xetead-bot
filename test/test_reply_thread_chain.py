"""봇이 한 게시물에 이어 여러 게시물을 올릴 때는 스레드로 한 줄로 잇는다 —
같은 게시물에 답글이 둘 달리면 흐름을 한 번에 따라 읽을 수 없다."""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from bot.main import MastodonBotListener  # noqa: E402
from test_bot_admin import _FakeMastodon, _make_state  # noqa: E402


def _listener():
    mastodon = _FakeMastodon()
    return mastodon, MastodonBotListener(mastodon, _make_state(), bot_acct="bot")


def test_reply_with_split_calc_returns_last_post_to_continue_from():
    """계산식이 여러 게시물로 나뉘면 이어지는 공지는 마지막 조각에 달아야
    한다 — 첫 게시물에 달면 계산식 조각과 같은 게시물에 나란히 붙는다."""
    mastodon, listener = _listener()
    calc = "\n".join(f"▹ 대상_{i} | (6 + 3[1d6]) × 2[계수] → -18" for i in range(40))

    head, tail = listener._reply_with_calc(1, "a", "unlisted", "▹ 요약", calc)

    calls = mastodon.status_post_calls
    assert len(calls) > 1
    assert calls[0]["in_reply_to_id"] == 1
    # _FakeMastodon은 게시물 id를 9000부터 차례로 매긴다.
    assert head["id"] == 9000
    assert tail["id"] == 9000 + len(calls) - 1


def test_reply_too_long_for_cw_returns_calc_followup_as_tail():
    mastodon, listener = _listener()
    text = "\n".join(f"▹ 대상_{i} | -10 → 90/100" for i in range(30))

    head, tail = listener._reply_with_calc(1, "a", "unlisted", text, "계산식 본문")

    calls = mastodon.status_post_calls
    assert calls[-1]["spoiler_text"] == "계산식"
    assert calls[-1]["in_reply_to_id"] == head["id"]
    assert tail["id"] == 9000 + len(calls) - 1
