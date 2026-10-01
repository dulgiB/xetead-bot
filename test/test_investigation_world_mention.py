"""상시전투 스레드의 봇 게시물은 맨 앞에 world와 참여자 전원을 함께 멘션한다."""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import PracticeBattleMode  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot import main as main_module  # noqa: E402
from bot.commands import admin as admin_module  # noqa: E402
from bot.main import (  # noqa: E402
    WORLD_MASTODON_ID,
    MastodonBotListener,
    _practice_post_mention_accts,
)
from bot.practice_state import PracticeBattleState  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from test_bot_admin import (  # noqa: E402
    _FakeMastodon,
    _make_notification,
    _make_state,
    _only_practice,
)

_ALLY_ACCT = "ally_acct"
_PREFIX = f"@{WORLD_MASTODON_ID} @{_ALLY_ACCT} "


def _setup(monkeypatch, ancestors: list[dict] | None = None):
    state = _make_state()
    state.session = None
    ally = get_test_preset("아군", attack_range=3)
    state.char_dict = {_ALLY_ACCT: ally}
    state.name_dict = {"아군": ally, "몬스터": get_test_preset("몬스터")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet, cache=None: (
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: (
            {},
            {},
            {},
            {},
            None,
            state.char_dict,
            state.name_dict,
            state.noncombat_char_dict,
        ),
    )
    for name in (
        "_persist_practice_prep",
        "_upsert_practice_field_row",
        "_update_practice_field_active_post",
        "_persist_battle_log",
    ):
        monkeypatch.setattr(main_module, name, lambda *a, **k: None)
    mastodon = _FakeMastodon(ancestors)
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")
    return state, mastodon, listener


def _start(state, mastodon, listener) -> PracticeBattleState:
    listener._process_notification(
        _make_notification(
            WORLD_MASTODON_ID,
            1,
            0,
            "묘사 지문\n\n[상시전투] [배치/몬스터/적군 4열]",
            extra_mentions=[_ALLY_ACCT],
        )
    )
    ps = _only_practice(state)
    assert ps.prep_post_id is not None
    listener._process_notification(
        _make_notification(_ALLY_ACCT, 2, ps.prep_post_id, "[4열]")
    )
    return ps


def test_prep_post_mentions_world_and_participants_up_front(monkeypatch):
    state, mastodon, listener = _setup(monkeypatch)
    listener._process_notification(
        _make_notification(
            WORLD_MASTODON_ID,
            1,
            0,
            "[상시전투] [배치/몬스터/적군 4열]",
            extra_mentions=[_ALLY_ACCT],
        )
    )

    prep = mastodon.status_post_calls[-1]["status"]
    assert prep.startswith(_PREFIX)
    assert prep.count(f"@{_ALLY_ACCT}") == 1
    assert "참여 대상: 아군" in prep


def test_start_post_mentions_world(monkeypatch):
    state, mastodon, listener = _setup(monkeypatch)
    _start(state, mastodon, listener)

    assert mastodon.status_post_calls[-1]["status"].startswith(_PREFIX)


def test_ally_command_reply_and_phase_post_mention_world(monkeypatch):
    state, mastodon, listener = _setup(monkeypatch)
    ps = _start(state, mastodon, listener)
    before = len(mastodon.status_post_calls)

    listener._process_notification(
        _make_notification(_ALLY_ACCT, 3, ps.active_post_id, "[공격/몬스터]")
    )

    posts = mastodon.status_post_calls[before:]
    # 커맨드 결과 답글(계산식 CW)과 적 차례로 넘어가는 공지
    assert len(posts) >= 2
    assert all(p["status"].startswith(_PREFIX) for p in posts)


def test_world_proxy_reply_mentions_participants_too(monkeypatch):
    state, mastodon, listener = _setup(monkeypatch)
    ps = _start(state, mastodon, listener)
    listener._process_notification(
        _make_notification(_ALLY_ACCT, 3, ps.active_post_id, "[공격/몬스터]")
    )
    before = len(mastodon.status_post_calls)

    listener._process_notification(
        _make_notification(
            WORLD_MASTODON_ID, 4, ps.active_post_id, "몬스터 [공격/아군]"
        )
    )

    posts = mastodon.status_post_calls[before:]
    assert posts
    assert all(p["status"].startswith(_PREFIX) for p in posts)


def test_practice_duel_posts_do_not_mention_world():
    ctx = PracticeBattlefieldContext({}, {}, mode=PracticeBattleMode.PRACTICE)
    ps = PracticeBattleState(
        context=ctx,
        manager=PracticeRoundManager(ctx),
        mode=PracticeBattleMode.PRACTICE,
        expected_accts=["a", "b"],
    )

    assert _practice_post_mention_accts(ps) == ["a", "b"]


def test_world_can_start_mid_thread_as_a_reply(monkeypatch):
    """[대련]/[결투]처럼 진행 중인 스레드(상시조사 등) 중간에 답글로 시작할
    수 있어야 한다 — 그 스레드에 진행 중인 상시전투가 없으면 프록시로
    해석되지 않는다. 스레드에 이미 등장한 계정은 멘션이 빠져도 참여한다."""
    ancestors = [{"id": 500, "account": {"acct": _ALLY_ACCT}, "mentions": []}]
    state, mastodon, listener = _setup(monkeypatch, ancestors)

    listener._process_notification(
        _make_notification(
            WORLD_MASTODON_ID,
            501,
            500,
            "묘사 지문\n\n[상시전투] [배치/몬스터/적군 4열]",
        )
    )

    ps = _only_practice(state)
    assert ps.expected_accts == [_ALLY_ACCT]
    prep = mastodon.status_post_calls[-1]
    assert prep["in_reply_to_id"] == 501
    assert prep["status"].startswith(_PREFIX)


def test_declarations_chained_in_a_thread_start_under_the_last_one(monkeypatch):
    """안내 - A의 선언 - B의 선언처럼 타래로 이어 선언해도 받아들이고,
    시작 게시물은 마지막 선언 아래에 이어 붙는다."""
    other = "other_acct"
    state, mastodon, listener = _setup(monkeypatch)
    state.char_dict[other] = get_test_preset("동료", attack_range=3)
    listener._process_notification(
        _make_notification(
            WORLD_MASTODON_ID,
            1,
            0,
            "[상시전투] [배치/몬스터/적군 4열]",
            extra_mentions=[_ALLY_ACCT, other],
        )
    )
    ps = _only_practice(state)
    listener._process_notification(
        _make_notification(_ALLY_ACCT, 2, ps.prep_post_id, "[3열]")
    )
    mastodon.status_context_ancestors = [
        {"id": ps.prep_post_id, "account": {"acct": "bot"}, "mentions": []},
        {"id": 2, "account": {"acct": _ALLY_ACCT}, "mentions": []},
    ]

    listener._process_notification(_make_notification(other, 3, 2, "[ 5 열 ]"))

    assert ps.active_post_id is not None
    start = mastodon.status_post_calls[-1]
    assert start["in_reply_to_id"] == 3
    assert "상시전투 시작" in start["status"]
