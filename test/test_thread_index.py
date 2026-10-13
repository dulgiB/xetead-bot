"""스레드 조상을 Mastodon 조회 없이, 봇이 본 게시물의 부모 관계로 찾는다.

대련처럼 서로의 답글에 이어 다는 스레드는 커맨드마다 조상 조회가 필요한데,
Mastodon의 스레드 조회는 스레드가 깊을수록 느려(조상 40여 개에서 2~3초)
그 시간이 고스란히 응답 지연이 된다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from bot.main import MastodonBotListener  # noqa: E402
from bot.thread_index import ThreadIndex  # noqa: E402
from test_bot_admin import _FakeMastodon  # noqa: E402
from test_practice_proxy_thread_scope import (  # noqa: E402
    ACTIVE_POST_ID,
    _make_practice,
    _make_state,
)


class _CountingMastodon(_FakeMastodon):
    def __init__(self, ancestors=None):
        super().__init__(ancestors)
        self.status_context_calls = 0

    def status_context(self, status_id):
        self.status_context_calls += 1
        return super().status_context(status_id)


class TestThreadIndex:
    def test_stops_at_nearest_wanted_ancestor(self):
        index = ThreadIndex()
        index.record(3, 2)
        index.record(2, 1)

        assert index.ancestor_ids(3, wanted={2, 1}) == {3, 2}

    def test_known_chain_up_to_root_is_complete(self):
        index = ThreadIndex()
        index.record(3, 2)
        index.record(2, None)

        assert index.ancestor_ids(3, wanted={99}) == {3, 2}

    def test_unknown_link_returns_none(self):
        index = ThreadIndex()
        index.record(3, 2)

        assert index.ancestor_ids(3, wanted={99}) is None

    def test_oldest_entries_are_evicted_over_limit(self):
        index = ThreadIndex(max_entries=2)
        index.record(1, None)
        index.record(2, 1)
        index.record(3, 2)

        assert index.ancestor_ids(3, wanted={99}) is None
        assert index.ancestor_ids(3, wanted={2}) == {3, 2}


class TestListenerThreadLookup:
    def _listener(self, mastodon):
        state = _make_state()
        ps = _make_practice(state)
        ps.expected_accts = ["acct_a"]
        return MastodonBotListener(mastodon, state, bot_acct="bot"), state, ps

    def test_reply_to_bot_post_resolves_without_thread_lookup(self):
        """봇이 진행 게시물 아래 올린 답글에 이어 단 커맨드는 조회 없이 찾는다."""
        mastodon = _CountingMastodon()
        listener, state, ps = self._listener(mastodon)
        bot_reply = listener._status_post("결과", in_reply_to_id=ACTIVE_POST_ID)

        resolved = listener._resolve_practice("acct_a", 901, bot_reply["id"], state)

        assert resolved is ps
        assert mastodon.status_context_calls == 0

    def test_reply_to_recorded_mention_resolves_without_thread_lookup(self):
        mastodon = _CountingMastodon()
        listener, state, ps = self._listener(mastodon)
        listener._threads.record(800, ACTIVE_POST_ID)

        assert listener._resolve_practice("acct_a", 901, 800, state) is ps
        assert mastodon.status_context_calls == 0

    def test_unknown_parent_falls_back_to_thread_lookup_once(self):
        """모르는 게시물(사담 등)에서 끊기면 조회하고, 그 결과를 기억한다."""
        mastodon = _CountingMastodon(
            ancestors=[
                {"id": ACTIVE_POST_ID, "in_reply_to_id": None},
                {"id": 700, "in_reply_to_id": ACTIVE_POST_ID},
            ]
        )
        listener, state, ps = self._listener(mastodon)

        assert listener._resolve_practice("acct_a", 901, 700, state) is ps
        assert listener._resolve_practice("acct_a", 902, 700, state) is ps
        assert mastodon.status_context_calls == 1

    def test_known_unrelated_thread_resolves_to_nothing_without_lookup(self):
        mastodon = _CountingMastodon()
        listener, state, _ps = self._listener(mastodon)
        top = listener._status_post("다른 공지")
        listener._threads.record(800, top["id"])

        assert listener._resolve_practice("acct_a", 901, 800, state) is None
        assert mastodon.status_context_calls == 0
