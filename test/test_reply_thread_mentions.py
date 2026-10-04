"""봇 답글은 웹 UI에서 답글을 달 때처럼 원 게시물의 작성자, 그 게시물의
멘션 순으로 스레드 참여자 전원을 멘션한다."""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from bot import main as main_module  # noqa: E402
from bot.main import ADMIN_MASTODON_ID, MastodonBotListener  # noqa: E402
from test_bot_admin import (  # noqa: E402
    _FakeMastodon,
    _make_notification,
    _make_state,
)


def _listener(monkeypatch):
    state = _make_state()
    state.session = None
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    mastodon = _FakeMastodon()
    return mastodon, MastodonBotListener(mastodon, state, bot_acct="bot")


def _reply_to(mastodon, listener, extra_mentions, acct=ADMIN_MASTODON_ID) -> str:
    listener._process_notification(
        _make_notification(acct, 10, 5, "[전투종료]", extra_mentions=extra_mentions)
    )
    post = mastodon.status_post_calls[-1]
    assert post["in_reply_to_id"] == 10
    return post["status"]


def test_mentions_author_then_the_posts_mentions_in_order(monkeypatch):
    mastodon, listener = _listener(monkeypatch)

    text = _reply_to(mastodon, listener, ["user_b", "user_a"])

    assert text.startswith(f"@{ADMIN_MASTODON_ID} @user_b @user_a ")


def test_alone_in_thread_mentions_only_the_author(monkeypatch):
    mastodon, listener = _listener(monkeypatch)

    text = _reply_to(mastodon, listener, [])

    assert text.startswith(f"@{ADMIN_MASTODON_ID} ")
    assert text.count("@") == 1


def test_does_not_mention_itself(monkeypatch):
    mastodon, listener = _listener(monkeypatch)

    text = _reply_to(mastodon, listener, ["user_a"])

    assert "@bot" not in text


def test_author_mentioned_in_own_post_appears_once(monkeypatch):
    mastodon, listener = _listener(monkeypatch)

    text = _reply_to(mastodon, listener, [ADMIN_MASTODON_ID, "user_a"])

    assert text.count(f"@{ADMIN_MASTODON_ID}") == 1
    assert text.startswith(f"@{ADMIN_MASTODON_ID} @user_a ")


def test_extra_mentions_follow_the_thread_without_duplicates():
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, _make_state(), bot_acct="bot")
    listener._reply_mentions = {10: ["user_b", "user_a"]}

    listener._reply(10, "user_b", "public", "본문", mention_accts=["user_a", "user_c"])

    assert mastodon.status_post_calls[-1]["status"].startswith(
        "@user_b @user_a @user_c 본문"
    )


def test_split_reply_repeats_the_mentions_on_every_chunk():
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, _make_state(), bot_acct="bot")
    listener._reply_mentions = {10: ["user_b", "user_a"]}
    text = "\n".join(f"▹ 대상_{i} | -10 → 90/100" for i in range(60))

    listener._reply(10, "user_b", "public", text)

    calls = mastodon.status_post_calls
    assert len(calls) > 1
    assert all(c["status"].startswith("@user_b @user_a ") for c in calls)
