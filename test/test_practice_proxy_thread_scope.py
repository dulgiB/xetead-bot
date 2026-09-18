"""admin/world 프록시가 어느 대련/상시전투에 속하는지는 **스레드로** 정한다.

이름만으로 세션을 고르면, 종료되지 않은 세션에 같은 이름이 남아 있을 때 다른
전장(본 전투 등)으로 보낸 프록시를 그 세션이 조용히 가져간다 — 오류도 로그도
없이 엉뚱한 세션의 페이즈 안내만 돌아온다. 동시에 여러 대련을 진행할 수 있어
이름이 겹칠 여지는 상시 존재한다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import pytest  # noqa: E402
from battle.objects.define import BattlefieldColumnIndex  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import (  # noqa: E402
    PracticeBattleMode,
    PracticeRoundPhase,
    SideType,
)
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot.main import (  # noqa: E402
    BotState,
    MastodonBotListener,
    _handle_practice_proxy_command,
)
from bot.practice_state import PracticeBattleState  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from test_bot_admin import _FakeMastodon  # noqa: E402

ACTIVE_POST_ID = 500
PREP_POST_ID = 400
FIELD_ID = "300"


def _make_state() -> BotState:
    return BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )


def _make_practice(
    state: BotState,
    *,
    mode: PracticeBattleMode = PracticeBattleMode.PRACTICE,
    names: tuple[str, str] = ("대련_1", "대련_2"),
    active_post_id: int = ACTIVE_POST_ID,
) -> PracticeBattleState:
    context = PracticeBattlefieldContext(buff_dict={}, skill_dict={}, mode=mode)
    context.add_character(
        get_test_preset(names[0]), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    context.add_character(
        get_test_preset(names[1]), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )
    ps = PracticeBattleState(
        context=context,
        manager=PracticeRoundManager(context),
        expected_accts=[],
        visibility="unlisted",
        mode=mode,
        active_post_id=active_post_id,
        round_limit=5,
    )
    ps.prep_post_id = PREP_POST_ID
    ps.field_id = FIELD_ID
    ps.round_n = 1
    ps.first_mover = SideType.SIDE_1
    ps.second_mover = SideType.SIDE_2
    ps.manager.set_phase_for_restore(
        PracticeRoundPhase.FIRST_MOVER_ACTION, SideType.SIDE_1, SideType.SIDE_2
    )
    state.practices[active_post_id] = ps
    return ps


def _resolve(
    listener: MastodonBotListener,
    state: BotState,
    in_reply_to_id,
    *,
    require_investigation: bool = False,
    status_id: int = 900,
):
    return listener._resolve_practice_for_proxy(
        status_id, in_reply_to_id, state, require_investigation=require_investigation
    )


class TestThreadResolution:
    def test_direct_reply_to_active_post_resolves(self):
        state = _make_state()
        ps = _make_practice(state)
        listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

        assert _resolve(listener, state, ACTIVE_POST_ID) is ps

    def test_top_level_post_resolves_to_nothing(self):
        """최상위 게시물은 어느 스레드에도 속하지 않는다 — 이름이 맞아도
        대련이 가져가면 안 된다."""
        state = _make_state()
        _make_practice(state)
        listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

        assert _resolve(listener, state, None) is None

    def test_unrelated_thread_resolves_to_nothing(self):
        state = _make_state()
        _make_practice(state)
        mastodon = _FakeMastodon(ancestors=[{"id": 999}])
        listener = MastodonBotListener(mastodon, state, bot_acct="bot")

        assert _resolve(listener, state, 998) is None

    def test_deeper_reply_in_the_same_thread_resolves(self):
        """페이즈 게시물에 직접 달지 않아도 같은 스레드면 인정한다 —
        캐릭터 본인 답글 경로(_resolve_practice)와 같은 규칙이다."""
        state = _make_state()
        ps = _make_practice(state)
        mastodon = _FakeMastodon(ancestors=[{"id": ACTIVE_POST_ID}])
        listener = MastodonBotListener(mastodon, state, bot_acct="bot")

        assert _resolve(listener, state, 998) is ps

    def test_field_id_post_counts_as_ancestor(self):
        state = _make_state()
        ps = _make_practice(state)
        mastodon = _FakeMastodon(ancestors=[{"id": int(FIELD_ID)}])
        listener = MastodonBotListener(mastodon, state, bot_acct="bot")

        assert _resolve(listener, state, 998) is ps

    def test_no_active_practice_skips_thread_lookup(self):
        """진행 중인 세션이 없으면 스레드 조회 자체를 하지 않는다 — 대련과
        무관한 고빈도 admin 멘션까지 매번 API를 한 번 더 쓰지 않도록."""
        state = _make_state()

        class _Exploding(_FakeMastodon):
            def status_context(self, status_id):
                raise AssertionError("스레드를 조회하면 안 된다")

        listener = MastodonBotListener(_Exploding(), state, bot_acct="bot")

        assert _resolve(listener, state, 998) is None

    def test_world_only_sees_investigation_sessions(self):
        state = _make_state()
        _make_practice(state, mode=PracticeBattleMode.PRACTICE)
        listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

        assert (
            _resolve(listener, state, ACTIVE_POST_ID, require_investigation=True)
            is None
        )

    def test_world_sees_investigation_session(self):
        state = _make_state()
        ps = _make_practice(state, mode=PracticeBattleMode.INVESTIGATION)
        listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

        assert (
            _resolve(listener, state, ACTIVE_POST_ID, require_investigation=True) is ps
        )

    def test_two_sessions_resolve_by_their_own_post(self):
        state = _make_state()
        first = _make_practice(state, names=("대련_1", "대련_2"))
        second = _make_practice(
            state, names=("대련_3", "대련_4"), active_post_id=ACTIVE_POST_ID + 1
        )
        listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

        assert _resolve(listener, state, ACTIVE_POST_ID) is first
        assert _resolve(listener, state, ACTIVE_POST_ID + 1) is second


class TestProxyHonoursTheResolvedSession:
    def test_no_session_processes_nothing(self):
        """세션이 정해지지 않으면 이름이 맞아도 한 줄도 처리하지 않고,
        호출측이 본 전투 라우팅으로 넘어갈 수 있게 ps=None을 돌려준다."""
        state = _make_state()
        _make_practice(state)

        *_, ps = _handle_practice_proxy_command(
            "◊ 대련_1 [이동/3]", state, "test-admin", session=None
        )

        assert ps is None

    def test_names_outside_the_session_are_ignored(self):
        state = _make_state()
        session = _make_practice(state)

        *_, ps = _handle_practice_proxy_command(
            "◊ 없는이름 [이동/3]", state, "test-admin", session=session
        )

        assert ps is None

    def test_participant_of_the_resolved_session_is_processed(self):
        state = _make_state()
        session = _make_practice(state)

        reply, _, _, _, _, ps = _handle_practice_proxy_command(
            "◊ 대련_1 [이동/3]", state, "test-admin", session=session
        )

        assert ps is session
        assert reply


class TestStaleSessionDoesNotHijack:
    """회귀 방지: 종료되지 않은 대련에 같은 이름이 있어도, 그 스레드 밖에서
    보낸 프록시는 가져가지 않는다."""

    @pytest.mark.parametrize("in_reply_to_id", [None, 998])
    def test_proxy_outside_the_thread_is_left_to_other_routing(self, in_reply_to_id):
        state = _make_state()
        _make_practice(state, names=("공용이름", "대련_2"))
        mastodon = _FakeMastodon(ancestors=[{"id": 777}])
        listener = MastodonBotListener(mastodon, state, bot_acct="bot")

        session = _resolve(listener, state, in_reply_to_id)
        *_, ps = _handle_practice_proxy_command(
            "◊ 공용이름 [이동/3]", state, "test-admin", session=session
        )

        assert session is None
        assert ps is None
