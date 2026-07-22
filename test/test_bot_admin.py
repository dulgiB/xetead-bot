import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import contextlib
import itertools
from pathlib import Path

from battle.objects.define import BattlefieldColumnIndex, FactionType  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import SideType  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot import log_sheets  # noqa: E402
from bot import main as main_module  # noqa: E402
from bot.commands import admin as admin_module  # noqa: E402
from bot.commands import character as character_module  # noqa: E402
from bot.commands.admin import (  # noqa: E402
    _cmd_advance_phase,
    _cmd_battle_start,
    _cmd_continue_battle,
)
from bot.main import BotState, MastodonBotListener  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402


def _make_state(**pending) -> BotState:
    state = BotState(
        char_dict={},
        name_dict={"유효 캐릭터": get_test_preset("유효 캐릭터")},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
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


def test_battle_start_marks_round_start_for_field_image():
    """[전투개시]는 라운드 1 시작이므로 game_post에 필드 시트 이미지를 붙여야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )

    result = _cmd_battle_start(state)

    assert result.attach_field_image is True


def test_advance_phase_always_marks_field_image():
    """필드 현황은 str 대신 이미지로만 표시하므로, 모든 페이즈 전환
    게시물(ALLY_ACTION, ENEMY_POST_ACTION, STANDBY 진입 모두)에 이미지를
    붙여야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)

    to_ally_action = _cmd_advance_phase(state)
    to_enemy_post_action = _cmd_advance_phase(state)
    to_standby = _cmd_advance_phase(state)

    assert to_ally_action.attach_field_image is True
    assert to_enemy_post_action.attach_field_image is True
    assert to_standby.attach_field_image is True


def test_enemy_post_action_summary_includes_calculation():
    """적 공격 정산(ENEMY_POST_ACTION) 게시물에도 대미지 계산식(↳ ...)이
    표시되어야 한다 — HP 증감 요약만으로는 계수/주사위 계산 과정이
    누락된다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)

    admin_module._cmd_proxy("적 캐릭터", "[공격/유효 캐릭터]", state)

    _cmd_advance_phase(state)  # → 아군 행동
    to_post_action = _cmd_advance_phase(state)  # → 적 공격 정산

    assert "↳" in to_post_action.game_post_text
    assert "적 캐릭터" in to_post_action.game_post_text


def test_proxy_pre_action_reply_prefixes_each_part_with_caster_name():
    """관리자 프록시로 대행한 PRE 선언 답글도 POST 정산과 마찬가지로,
    CommandPart(파트)별 헤더 앞에 대행한 캐릭터의 이름이 붙어야 한다 —
    답글 자체만으로는 누가 행동했는지 알 수 없기 때문이다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    _cmd_battle_start(state)

    reply_text, _battle_log = admin_module._cmd_proxy(
        "적 캐릭터", "[이동/3열 - 공격/유효 캐릭터]", state
    )

    assert reply_text == (
        "적 캐릭터 【이동 ▸ 3열】\n\n"
        "적 캐릭터 【공격 ▸ 유효 캐릭터】"
    )


def test_continue_battle_marks_round_start_for_field_image():
    """[전투속행]은 다음 라운드 시작(ENEMY_PRE_ACTION 진입)이므로 이미지를
    붙여야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)
    for _ in range(3):  # ALLY_ACTION → ENEMY_POST_ACTION → STANDBY
        _cmd_advance_phase(state)

    result = _cmd_continue_battle(state)

    assert result.attach_field_image is True


def test_investigation_battle_inline_placement_respects_faction_token(monkeypatch):
    """[상시전투]와 함께 입력된 [배치/이름/아군 3열]은 '아군' 토큰대로
    SIDE_1(아군)에 배치되어야 하며, 무조건 적(SIDE_2)으로 배치되면 안 된다."""
    state = _make_state()
    state.name_dict = {"동료": get_test_preset("동료")}
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet: (
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
        self._next_media_id = itertools.count(1000)
        self.media_post_calls: list[str] = []
        self.status_post_calls: list[dict] = []
        self.last_media_id: int = 0

    def status_post(self, *args, **kwargs):
        if args:
            kwargs = {**kwargs, "status": args[0]}
        self.status_post_calls.append(kwargs)
        return {"id": next(self._next_id)}

    def media_post(self, media_file, *args, **kwargs):
        self.media_post_calls.append(str(media_file))
        self.last_media_id = next(self._next_media_id)
        return {"id": self.last_media_id}


def _make_notification(
    acct: str,
    status_id: int,
    in_reply_to_id: int,
    text: str,
    visibility: str = "public",
    extra_mentions: list[str] | None = None,
) -> dict:
    mentions = [{"acct": "bot"}] + [{"acct": a} for a in (extra_mentions or [])]
    return {
        "type": "mention",
        "account": {"acct": acct},
        "status": {
            "id": status_id,
            "content": f"<p>@bot {text}</p>",
            "visibility": visibility,
            "in_reply_to_id": in_reply_to_id,
            "mentions": mentions,
        },
    }


def test_replying_again_to_stale_prep_post_does_not_restart_battle(monkeypatch):
    """포지션 선언이 완료되어 전투가 시작된 뒤, 같은 참가자가 실수로 원본
    준비 게시물에 다시 답글을 달아도 전투가 재시작되면 안 된다."""
    state = _make_state()
    state.char_dict = {"user1": get_test_preset("동료")}
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )

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


def test_battle_prep_posts_as_new_status_not_reply(monkeypatch):
    """[전투준비] 공지는 답글이 아니라 타임라인의 새 게시물로 올라가야 하고,
    이후 참가 신청 답글이 그 게시물을 정상적으로 대상 삼을 수 있어야 한다."""
    state = _make_state()
    state.session = None
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )
    monkeypatch.setattr(admin_module, "load_battle_data", lambda spreadsheet: (
        {}, {}, {}, {}, None, state.char_dict, state.name_dict, state.noncombat_char_dict
    ))
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투준비]"))

    assert len(mastodon.status_post_calls) == 1
    prep_call = mastodon.status_post_calls[0]
    assert "in_reply_to_id" not in prep_call
    assert "전투 준비" in prep_call["status"]

    prep_post_id = state.preparation_status_id
    state.char_dict["ally_acct"] = get_test_preset("유효 캐릭터")
    listener.on_notification(
        _make_notification("ally_acct", 2, prep_post_id, "아무 코멘트")
    )

    assert "ally_acct" in state.pending_participants


def test_malformed_notification_does_not_raise():
    """형식이 예상과 다른(status가 없는 등) 알림이 와도 예외가 밖으로
    전파되면 안 된다 — 스트리밍 리스너 전체가 죽는 것을 방지한다."""
    state = _make_state()
    listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

    listener.on_notification({"type": "mention", "account": {"acct": "user1"}})


@contextlib.contextmanager
def _fake_capture(spreadsheet):
    yield Path("/tmp/fake-field.png")


def test_capture_field_media_ids_uploads_and_returns_media_id(monkeypatch):
    """캡처가 성공하면 업로드된 media_id를 리스트로 반환해야 한다."""
    state = _make_state()
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    media_ids = listener._capture_field_media_ids(state)

    assert media_ids == [mastodon.last_media_id]
    assert mastodon.media_post_calls == ["/tmp/fake-field.png"]


def test_capture_field_media_ids_absorbs_exception(monkeypatch):
    """캡처/업로드 실패는 예외를 흡수하고 빈 리스트를 반환해야 한다 —
    이 실패가 답글 전송 자체를 막으면 안 된다."""

    @contextlib.contextmanager
    def failing_capture(spreadsheet):
        raise RuntimeError("network boom")
        yield  # pragma: no cover

    state = _make_state()
    monkeypatch.setattr(main_module, "capture_field_sheet_image", failing_capture)
    listener = MastodonBotListener(_FakeMastodon(), state, bot_acct="bot")

    assert listener._capture_field_media_ids(state) == []


def test_round_start_game_post_attaches_field_image(monkeypatch):
    """[전투개시] 공개 게시물(라운드 시작 알림)에 필드 시트 이미지가 첨부되어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification("test-admin", 1, 0, "[전투개시]")
    )

    public_posts = [
        c for c in mastodon.status_post_calls if "in_reply_to_id" not in c
    ]
    assert len(public_posts) == 1
    assert public_posts[0]["media_ids"] == [mastodon.last_media_id]
    # 본 전투 페이즈 게시물은 visibility를 강제하지 않고 계정/서버 기본값을
    # 따라야 한다 — "public"으로 하드코딩하면 안 된다.
    assert "visibility" not in public_posts[0]


def test_character_command_reply_has_no_image_but_keeps_text(monkeypatch):
    """본 전투의 캐릭터 커맨드 답글은 이미지를 첨부하지 않고 텍스트만
    보내야 한다 — 필드 시트 이미지는 페이즈 게시물 전용이다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ]
    )
    state.name_dict["적 캐릭터"] = get_test_preset("적 캐릭터")
    state.pending_placements.append(
        ("적 캐릭터", FactionType.ENEMY, BattlefieldColumnIndex(0))
    )
    state.char_dict["ally_acct"] = get_test_preset("유효 캐릭터")
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    monkeypatch.setattr(character_module, "write_back_changed_hp", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투개시]"))
    listener.on_notification(_make_notification("test-admin", 2, 0, "[진행]"))
    active_post_id = state.active_phase_post_id

    listener.on_notification(
        _make_notification("ally_acct", 3, active_post_id, "[공격/적 캐릭터]")
    )

    reply_calls = [
        c for c in mastodon.status_post_calls if "in_reply_to_id" in c
    ]
    char_reply = reply_calls[-1]
    assert char_reply["media_ids"] is None
    assert "공격" in char_reply["status"]


def test_ally_action_phase_post_attaches_field_image(monkeypatch):
    """필드 현황은 str 대신 이미지로만 표시하므로, 일반 페이즈 전환
    공개 게시물(아군 행동 등)에도 이미지가 붙어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification("test-admin", 1, 0, "[진행]")
    )

    public_posts = [
        c for c in mastodon.status_post_calls if "in_reply_to_id" not in c
    ]
    assert len(public_posts) == 1
    assert public_posts[0]["media_ids"] == [mastodon.last_media_id]


def test_phase_post_falls_back_to_text_board_when_image_capture_fails(monkeypatch):
    """이미지 캡처가 실패하면 게시물 텍스트에 str(context) 필드 보드를
    대체 표시해야 한다 (정보가 완전히 유실되면 안 되므로)."""

    @contextlib.contextmanager
    def _failing_capture(spreadsheet):
        raise RuntimeError("capture boom")
        yield  # pragma: no cover

    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)
    monkeypatch.setattr(
        main_module,
        "load_char_data",
        lambda spreadsheet: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _failing_capture)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification("test-admin", 1, 0, "[진행]")
    )

    public_posts = [
        c for c in mastodon.status_post_calls if "in_reply_to_id" not in c
    ]
    assert len(public_posts) == 1
    assert public_posts[0]["media_ids"] is None
    assert "유효 캐릭터" in public_posts[0]["status"]


def test_practice_session_posts_thread_together_with_matching_visibility(
    monkeypatch,
):
    """대련 세션의 모든 게시물은 최초 [대련] 개시 멘션의 visibility를 따르고,
    서로 답글로 이어져 하나의 스레드를 이뤄야 한다 — 매번 독립된 공개
    게시물로 흩어지면 안 된다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    name_dict = {"검사": get_test_preset("검사"), "궁수": get_test_preset("궁수")}
    monkeypatch.setattr(
        main_module, "load_char_data", lambda spreadsheet: (char_dict, name_dict, {})
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet: ({}, {}, {}, {}, None, char_dict, name_dict, {}),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[대련]",
            visibility="unlisted",
            extra_mentions=["swordsman_acct", "archer_acct"],
        )
    )
    prep_call = mastodon.status_post_calls[-1]
    assert prep_call["visibility"] == "unlisted"
    assert prep_call["in_reply_to_id"] == 1
    prep_post_id = state.practice.prep_post_id

    listener.on_notification(
        _make_notification("swordsman_acct", 2, prep_post_id, "[1팀/3열]")
    )
    listener.on_notification(
        _make_notification("archer_acct", 3, prep_post_id, "[2팀/5열]")
    )
    start_call = mastodon.status_post_calls[-1]
    assert start_call["visibility"] == "unlisted"
    assert start_call["in_reply_to_id"] == prep_post_id

    active_post_id = state.practice.active_post_id
    first_acct, second_name = (
        ("swordsman_acct", "궁수")
        if state.practice.first_mover.value == "1팀"
        else ("archer_acct", "검사")
    )
    listener.on_notification(
        _make_notification(
            first_acct, 4, active_post_id, f"[공격/{second_name}]"
        )
    )
    round_call = mastodon.status_post_calls[-1]
    assert round_call["visibility"] == "unlisted"
    assert round_call["in_reply_to_id"] == active_post_id
