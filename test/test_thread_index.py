"""스레드 조상을 봇이 본 게시물의 부모 관계로 찾고, 모르는 게시물만 하나씩
조회한다.

Mastodon의 스레드 조회는 스레드 전체를 돌려줘 깊은 RP 스레드에서 20초가 넘게
걸린다. 세션 게시물은 스레드 중간에 있으므로 거기까지만 올라가면 된다.
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
        self.status_calls: list[int] = []

    def status_context(self, status_id):
        raise AssertionError("스레드 전체를 조회하면 안 된다")

    def status(self, status_id):
        self.status_calls.append(status_id)
        return super().status(status_id)


class TestThreadIndex:
    def test_stops_at_nearest_wanted_ancestor(self):
        index = ThreadIndex()
        index.record(3, 2)
        index.record(2, 1)

        assert index.ancestor_ids(3, wanted={2, 1}) == ({3, 2}, None)

    def test_known_chain_up_to_root_is_complete(self):
        index = ThreadIndex()
        index.record(3, 2)
        index.record(2, None)

        assert index.ancestor_ids(3, wanted={1}) == ({3, 2}, None)

    def test_unknown_link_is_reported(self):
        index = ThreadIndex()
        index.record(3, 2)

        assert index.ancestor_ids(3, wanted={1}) == ({3, 2}, 2)

    def test_stops_above_the_oldest_wanted_post(self):
        index = ThreadIndex()
        index.record(30, 20)

        assert index.ancestor_ids(30, wanted={25}) == ({30, 20}, None)

    def test_oldest_entries_are_evicted_over_limit(self):
        index = ThreadIndex(max_entries=2)
        index.record(1, None)
        index.record(2, 1)
        index.record(3, 2)

        assert index.ancestor_ids(3, wanted={0}) == ({3, 2, 1}, 1)
        assert index.ancestor_ids(3, wanted={2}) == ({3, 2}, None)

    def test_author_is_recorded_and_evicted_with_the_post(self):
        """작성자도 부모와 함께 기록되고 함께 밀려난다(테스트)."""
        index = ThreadIndex(max_entries=2)
        index.record(1, None, "acct_a")
        index.record(2, 1)
        index.record(3, 2, "acct_b")

        assert index.author_of(1) is None
        assert index.author_of(2) is None
        assert index.author_of(3) == "acct_b"


class TestListenerThreadLookup:
    def _listener(self, mastodon):
        state = _make_state()
        ps = _make_practice(state)
        ps.expected_accts = ["acct_a"]
        return MastodonBotListener(mastodon, state, bot_acct="bot"), state, ps

    def test_reply_to_bot_post_resolves_without_lookup(self):
        """봇이 진행 게시물 아래 올린 답글에 이어 단 커맨드는 조회 없이 찾는다."""
        mastodon = _CountingMastodon()
        listener, state, ps = self._listener(mastodon)
        bot_reply = listener._status_post("결과", in_reply_to_id=ACTIVE_POST_ID)

        resolved = listener._resolve_practice("acct_a", 9901, bot_reply["id"], state)

        assert resolved is ps
        assert mastodon.status_calls == []

    def test_reply_to_recorded_mention_resolves_without_lookup(self):
        mastodon = _CountingMastodon()
        listener, state, ps = self._listener(mastodon)
        listener._threads.record(800, ACTIVE_POST_ID)

        assert listener._resolve_practice("acct_a", 901, 800, state) is ps
        assert mastodon.status_calls == []

    def test_unknown_posts_are_fetched_one_by_one_up_to_the_session_post(self):
        mastodon = _CountingMastodon(
            ancestors=[
                {"id": 100, "in_reply_to_id": None},
                {"id": ACTIVE_POST_ID, "in_reply_to_id": 100},
                {"id": 700, "in_reply_to_id": ACTIVE_POST_ID},
                {"id": 701, "in_reply_to_id": 700},
            ]
        )
        listener, state, ps = self._listener(mastodon)

        assert listener._resolve_practice("acct_a", 902, 701, state) is ps
        assert listener._resolve_practice("acct_a", 903, 701, state) is ps
        assert mastodon.status_calls == [701, 700]

    def test_fetched_and_bot_posts_record_their_authors(self):
        """조회로 이어 간 게시물과 봇 게시물도 작성자가 남는다 — 일반 의뢰
        [수락]이 스레드 작성자를 API 없이 다시 읽는다(테스트)."""
        mastodon = _CountingMastodon(
            ancestors=[
                {"id": ACTIVE_POST_ID, "in_reply_to_id": None},
                {
                    "id": 700,
                    "in_reply_to_id": ACTIVE_POST_ID,
                    "account": {"acct": "acct_b"},
                },
            ]
        )
        listener, state, _ps = self._listener(mastodon)
        bot_post = listener._status_post("공지")

        listener._thread_ancestor_ids(700, (ACTIVE_POST_ID,))

        assert listener._threads.author_of(700) == "acct_b"
        assert listener._threads.author_of(bot_post["id"]) == "bot"

    def test_unrelated_thread_stops_below_the_session_start(self):
        """세션 게시물보다 오래된 게시물에 닿으면 그 위는 조회하지 않는다."""
        mastodon = _CountingMastodon(
            ancestors=[
                {"id": 100, "in_reply_to_id": None},
                {"id": 299, "in_reply_to_id": 100},
                {"id": 650, "in_reply_to_id": 299},
            ]
        )
        listener, state, _ps = self._listener(mastodon)

        assert listener._resolve_practice("acct_a", 901, 650, state) is None
        assert mastodon.status_calls == [650]

    def test_deleted_parent_ends_the_thread(self):
        from mastodon import MastodonNotFoundError

        mastodon = _CountingMastodon()
        listener, state, _ps = self._listener(mastodon)

        def _deleted(status_id):
            raise MastodonNotFoundError("삭제됨")

        mastodon.status = _deleted  # type: ignore[method-assign]

        assert listener._resolve_practice("acct_a", 901, 650, state) is None
        assert listener._threads.ancestor_ids(650, [ACTIVE_POST_ID]) == ({650}, None)

    def test_known_unrelated_thread_resolves_to_nothing_without_lookup(self):
        mastodon = _CountingMastodon()
        listener, state, _ps = self._listener(mastodon)
        top = listener._status_post("다른 공지")
        listener._threads.record(800, top["id"])

        assert listener._resolve_practice("acct_a", 901, 800, state) is None
        assert mastodon.status_calls == []


class TestMastodonPyStringIds:
    """Mastodon.py 2.x는 게시물 id를 `str` 하위 타입(`MaybeSnowflakeIdType`)으로
    돌려준다. 봇 상태 일부(field_id → 정수 변환 등)와 섞여도 같은 게시물로
    봐야 한다 — 다르게 보면 상시전투 world 프록시처럼 현재 진행 게시물을
    거치지 않는 답글이 스레드 루트까지 조회된 뒤 조용히 무시된다."""

    @staticmethod
    def _id(value: int):
        from mastodon.types_base import MaybeSnowflakeIdType

        return MaybeSnowflakeIdType(str(value))

    def test_string_ids_match_integer_wanted_ids(self):
        """문자열 id로 기록한 조상도 정수 id로 찾는다(테스트)."""
        index = ThreadIndex()
        index.record(self._id(30), self._id(20), "acct_a")
        index.record(self._id(20), self._id(10))

        assert index.ancestor_ids(self._id(30), wanted={10}) == ({30, 20, 10}, None)
        assert index.author_of(self._id(30)) == "acct_a"

    def _started_session(self, mastodon):
        """시작 후 상태 그대로의 세션: 게시물 id는 문자열 계열, prep_post_id는
        0, field_id는 준비 게시물 id 문자열."""
        state = _make_state()
        ps = _make_practice(state)
        state.practices.pop(ACTIVE_POST_ID)
        ps.active_post_id = self._id(500)
        ps.prep_post_id = 0
        ps.field_id = "300"
        ps.expected_accts = ["acct_a"]
        state.practices[ps.active_post_id] = ps
        return MastodonBotListener(mastodon, state, bot_acct="bot"), state, ps

    def test_reply_under_an_older_phase_post_resolves_through_field_id(self):
        """지난 페이즈 공지 아래 사담에 단 world 프록시는 현재 진행 게시물을
        거치지 않아도 준비 게시물(field_id)로 같은 스레드로 본다(테스트)."""
        mastodon = _CountingMastodon()
        listener, state, ps = self._started_session(mastodon)
        listener._threads.record(self._id(300), self._id(200))
        listener._threads.record(self._id(350), self._id(300))
        listener._threads.record(self._id(700), self._id(350), "acct_a")

        resolved = listener._resolve_practice_for_proxy(
            901, self._id(700), state, require_investigation=False
        )

        assert resolved is ps
        assert mastodon.status_calls == []

    def test_started_session_still_stops_below_the_session_start(self):
        """시작 후 prep_post_id(0)가 조기 종료 기준을 0으로 끌어내리지 않는다 —
        세션보다 오래된 게시물에 닿으면 그 위는 조회하지 않는다(테스트)."""
        mastodon = _CountingMastodon(
            ancestors=[
                {"id": 100, "in_reply_to_id": None},
                {"id": 299, "in_reply_to_id": 100},
                {"id": 650, "in_reply_to_id": 299},
            ]
        )
        listener, state, _ps = self._started_session(mastodon)

        assert listener._resolve_practice("acct_a", 901, self._id(650), state) is None
        assert mastodon.status_calls == [650]
