import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import contextlib
import itertools
from pathlib import Path

from battle.objects.buff.buff_base import BuffAddData  # noqa: E402
from battle.objects.buff.models import BuffData  # noqa: E402
from battle.objects.define import (  # noqa: E402
    BattlefieldColumnIndex,
    FactionType,
    ValueType,
)
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
from bot.main import BotState, MastodonBotListener, _handle_practice_command  # noqa: E402
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


def test_battle_start_reports_error_for_defeated_participant():
    """참전 신청자 중 체력이 0인 캐릭터는 무작위 자동 배치 중 예전에는
    조용히 사라졌다 — 이제는 오류로 보고되어 관리자가 알 수 있어야 하고,
    나머지 참전 신청자는 정상적으로 배치되어야 한다."""
    state = _make_state(pending_participants=["dead_acct", "alive_acct"])
    state.char_dict = {
        "dead_acct": get_test_preset("탈락캐릭터", initial_hp=0),
        "alive_acct": get_test_preset("생존캐릭터"),
    }

    result = _cmd_battle_start(state)

    assert state.session.started is True
    assert CharacterId("생존캐릭터") in state.session.context.characters
    assert CharacterId("탈락캐릭터") not in state.session.context.characters
    assert "탈락캐릭터" in result.reply_text


def test_advance_phase_system_error_is_generic_and_logged(monkeypatch, caplog):
    """스프레드시트 저장/렌더링 실패는 원본 예외 메시지 대신 통일된
    "◊ 시스템 오류입니다."로만 노출되고, 전체 트레이스는 서버 로그에
    남아야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )
    _cmd_battle_start(state)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 API 내부 세부사항")

    monkeypatch.setattr(admin_module, "upsert_field_row", _boom)

    import logging

    with caplog.at_level(logging.ERROR, logger="bot.commands.admin"):
        result = _cmd_advance_phase(state)

    assert "◊ 시스템 오류입니다." in result.reply_text
    assert "시트 API 내부 세부사항" not in result.reply_text
    assert any(
        "필드 시트 저장 실패" in record.message and record.exc_info is not None
        for record in caplog.records
    )


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


def test_enemy_post_action_summary_includes_calculation(monkeypatch):
    """적 공격 정산(ENEMY_POST_ACTION) 게시물에도 대미지 계산식(↳ ...)이
    표시되어야 한다 — HP 증감 요약만으로는 계수/주사위 계산 과정이
    누락된다."""
    monkeypatch.setattr(log_sheets, "_load_hp_write_targets", lambda spreadsheet, cache=None: {})
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


def test_advance_phase_writes_back_post_action_damage(monkeypatch):
    """적 공격 정산(ENEMY_POST_ACTION) 시 발생한 대미지도 "캐릭터" 시트에
    반영되어야 한다 — 이전에는 개별 캐릭터 커맨드/프록시에서만 write-back이
    호출되고 POST_ACTION 정산 자체는 반영되지 않는 갭이 있었다."""

    class _RecordingWorksheet:
        def __init__(self, row_to_name: dict[int, str]):
            self._row_to_name = row_to_name
            self.recorded_hp: dict = {}

        def update_cell(self, row, col, value):
            self.recorded_hp[self._row_to_name[row]] = value

    ws = _RecordingWorksheet({2: "유효 캐릭터", 3: "적 캐릭터"})
    monkeypatch.setattr(
        log_sheets,
        "_load_hp_write_targets",
        lambda spreadsheet, cache=None: {
            "유효 캐릭터": (ws, 2, 1),
            "적 캐릭터": (ws, 3, 1),
        },
    )
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
    _cmd_advance_phase(state)  # → 적 공격 정산

    assert "유효 캐릭터" in ws.recorded_hp


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
        lambda spreadsheet, cache=None: (state.char_dict, state.name_dict, state.noncombat_char_dict),
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
        lambda spreadsheet, cache=None: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )
    monkeypatch.setattr(admin_module, "load_battle_data", lambda spreadsheet, cache=None: (
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
def _fake_capture(spreadsheet, cache=None):
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
    def failing_capture(spreadsheet, cache=None):
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
        lambda spreadsheet, cache=None: (state.char_dict, state.name_dict, state.noncombat_char_dict),
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
        lambda spreadsheet, cache=None: (state.char_dict, state.name_dict, state.noncombat_char_dict),
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
    # "@계정 커맨드파트헤더"처럼 멘션 바로 뒤에 내용이 붙으면 가독성이
    # 나빠지므로, 멘션 다음은 줄바꿈으로 시작해야 한다.
    assert char_reply["status"].startswith("@ally_acct\n")


def test_character_command_with_two_bracket_groups_is_rejected_with_explicit_error(
    monkeypatch,
):
    """캐릭터 계정이 대괄호를 두 개로 나눠 보내면(예: '[A] [B]'), 파서의 탐욕적
    매칭 때문에 하나만 조용히 처리되고 나머지가 사라지는 문제가 있었다 —
    본 전투 경로에서도 사전에 걸러 명시적 에러를 내야 한다."""
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
        lambda spreadsheet, cache=None: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )
    monkeypatch.setattr(main_module, "capture_field_sheet_image", _fake_capture)
    monkeypatch.setattr(character_module, "write_back_changed_hp", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(_make_notification("test-admin", 1, 0, "[전투개시]"))
    listener.on_notification(_make_notification("test-admin", 2, 0, "[진행]"))
    active_post_id = state.active_phase_post_id

    listener.on_notification(
        _make_notification(
            "ally_acct", 3, active_post_id, "[공격/적 캐릭터] [공격/적 캐릭터]"
        )
    )

    reply_calls = [c for c in mastodon.status_post_calls if "in_reply_to_id" in c]
    char_reply = reply_calls[-1]
    assert "대괄호 커맨드를 하나만" in char_reply["status"]


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
        lambda spreadsheet, cache=None: (state.char_dict, state.name_dict, state.noncombat_char_dict),
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
    def _failing_capture(spreadsheet, cache=None):
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
        lambda spreadsheet, cache=None: (state.char_dict, state.name_dict, state.noncombat_char_dict),
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
        main_module, "load_char_data", lambda spreadsheet, cache=None: (char_dict, name_dict, {})
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: ({}, {}, {}, {}, None, char_dict, name_dict, {}),
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
    calls_before_action = len(mastodon.status_post_calls)
    listener.on_notification(
        _make_notification(
            first_acct, 4, active_post_id, f"[공격/{second_name}]"
        )
    )
    # 캐릭터의 커맨드 답글이 이 액션으로 발생하는 첫 번째 게시물이다 — 다음
    # 라운드 공지는 예전 라운드 공지(active_post_id)가 아니라 이 답글에
    # 이어져야 스레드가 갈라지지 않는다.
    char_reply_id = 9000 + calls_before_action
    round_call = mastodon.status_post_calls[-1]
    assert round_call["visibility"] == "unlisted"
    assert round_call["in_reply_to_id"] == char_reply_id
    assert round_call["in_reply_to_id"] != active_post_id


def test_practice_ends_immediately_when_round_end_dot_wipes_a_side():
    """대련은 이미 공격으로 한쪽이 즉시 전멸하면 그 자리에서 승자를 선언하고
    종료된다. 이 테스트는 그중 놓치기 쉬운 경로 하나를 확인한다 — 후공 차례
    처리 중 ps.end_round()가 적용하는 라운드 종료 DoT로 전멸이 일어나는
    경우도, 다음 라운드까지 기다리지 않고 그 즉시 종료되어야 한다(HP는
    end_round() 이후에 다시 계산해야 한다)."""
    dot_buff = BuffData(
        id="맹독",
        buff_class_name="BuffDamageOverTime",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=999,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
    )
    ctx = PracticeBattlefieldContext(buff_dict={"맹독": dot_buff}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("A"), applied_to=CharacterId("B"), buff_id="맹독"
        )
    )

    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(context=ctx, manager=manager, round_limit=5)
    ps.start_round()

    side_to_acct = {SideType.SIDE_1: "acct_a", SideType.SIDE_2: "acct_b"}
    state = BotState(
        char_dict={
            "acct_a": get_test_preset("A"),
            "acct_b": get_test_preset("B"),
        },
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
    )
    state.practice = ps

    first_acct = side_to_acct[ps.first_mover]
    _, game_post, _ = _handle_practice_command(first_acct, "[이동/2]", state)
    assert "종료" not in game_post  # 아직 전멸 전 — 라운드가 계속돼야 한다

    second_acct = side_to_acct[ps.second_mover]
    _, game_post, _ = _handle_practice_command(second_acct, "[이동/2]", state)

    assert "종료" in game_post
    assert "승자: 1팀" in game_post
    assert state.practice is None


def test_practice_command_with_two_bracket_groups_is_rejected_with_explicit_error():
    """캐릭터 계정이 대괄호를 두 개로 나눠 보내면(예: '[A] [B]'), 파서의 탐욕적
    매칭 때문에 하나만 조용히 처리되고 나머지가 사라지는 문제가 있었다 —
    대련/상시전투 경로에서도 사전에 걸러 명시적 에러를 내야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(context=ctx, manager=manager, round_limit=5)
    ps.start_round()

    state = BotState(
        char_dict={"acct_a": get_test_preset("A")},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
    )
    state.practice = ps

    reply, game_post, battle_log = _handle_practice_command(
        "acct_a", "[이동/2] [이동/3]", state
    )

    assert "대괄호 커맨드를 하나만" in reply
    assert game_post is None
    assert battle_log is None


def test_practice_declaration_out_of_range_column_gets_error_reply_and_can_retry(
    monkeypatch,
):
    """[N팀/9열]처럼 열 번호가 범위를 벗어나면 예전에는 완전히 무응답이었다 —
    이제는 본 전투와 동일하게 validation error를 답글로 보내고, 이후
    올바른 형식으로 다시 보내면 정상적으로 선언이 성립해야 한다."""
    state = _make_state()
    char_dict = {
        "swordsman_acct": get_test_preset("검사"),
        "archer_acct": get_test_preset("궁수"),
    }
    name_dict = {"검사": get_test_preset("검사"), "궁수": get_test_preset("궁수")}
    monkeypatch.setattr(
        main_module, "load_char_data", lambda spreadsheet, cache=None: (char_dict, name_dict, {})
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: ({}, {}, {}, {}, None, char_dict, name_dict, {}),
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
    prep_post_id = state.practice.prep_post_id

    listener.on_notification(
        _make_notification("swordsman_acct", 2, prep_post_id, "[1팀/9열]")
    )

    error_reply = mastodon.status_post_calls[-1]
    assert "인식할 수 없습니다" in error_reply["status"]
    assert "swordsman_acct" not in state.practice.declared

    # 형식을 고쳐 재시도하면 정상적으로 선언이 성립해야 한다.
    listener.on_notification(
        _make_notification("swordsman_acct", 3, prep_post_id, "[1팀/3열]")
    )
    assert "swordsman_acct" in state.practice.declared


def _setup_dm_battle_state(monkeypatch, enemy_max_hp: int = 100):
    """DM 전투 테스트 공용 셋업. (mastodon, listener, state, char_dict, name_dict) 반환.

    "전사"는 아군 랜덤 배치로 어느 열에 놓이든 "고블린"을 공격할 수 있어야
    하므로 attack_range를 전체 열 폭(7)으로 넉넉히 잡는다 — 그렇지 않으면
    무작위 배치 결과에 따라 사거리 밖 판정으로 테스트가 간헐적으로 실패한다.
    """
    monkeypatch.setattr(log_sheets, "_load_hp_write_targets", lambda spreadsheet, cache=None: {})
    state = _make_state()
    char_dict = {"player_acct": get_test_preset("전사", attack_range=7)}
    name_dict = {
        "전사": get_test_preset("전사", attack_range=7),
        "고블린": get_test_preset("고블린", max_hp=enemy_max_hp),
    }
    monkeypatch.setattr(
        main_module, "load_char_data", lambda spreadsheet, cache=None: (char_dict, name_dict, {})
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: ({}, {}, {}, {}, None, char_dict, name_dict, {}),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")
    return mastodon, listener, state, char_dict, name_dict


def test_dm_battle_start_places_enemy_by_command_and_allies_by_mention(monkeypatch):
    """[전투 발생][배치/이름/열]은 적만 그 위치에 배치하고, admin이 함께
    멘션한 계정 중 char_dict에 등록된 캐릭터는 참전 신청 없이 자동으로
    아군 무작위 배치되어야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )

    assert len(state.dm_battles) == 1
    dm_state = next(iter(state.dm_battles.values()))
    goblin_id = CharacterId("고블린")
    warrior_id = CharacterId("전사")
    assert goblin_id in dm_state.session.context.characters
    assert warrior_id in dm_state.session.context.characters
    assert dm_state.session.context.characters[goblin_id].faction == FactionType.ENEMY
    assert dm_state.session.context.characters[warrior_id].faction == FactionType.ALLY
    assert (
        dm_state.session.context.find_character_position(goblin_id)
        == BattlefieldColumnIndex.from_str("1열")
    )
    assert dm_state.session.started is True


def test_dm_battle_start_silently_accepts_faction_prefixed_column(monkeypatch):
    """DM 전투의 [배치/이름/열]은 진영 지정이 없는 문법이지만(배치 대상이
    항상 적군으로 고정), 본 전투 문법인 [배치/이름/적군 N열]을 실수로 그대로
    써도 에러 없이 "적군" 부분을 무시하고 열만 적용해야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/적군 1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )

    assert len(state.dm_battles) == 1
    dm_state = next(iter(state.dm_battles.values()))
    goblin_id = CharacterId("고블린")
    assert goblin_id in dm_state.session.context.characters
    assert (
        dm_state.session.context.find_character_position(goblin_id)
        == BattlefieldColumnIndex.from_str("1열")
    )


def test_dm_battle_thread_visibility_and_wipe_ends_automatically(monkeypatch):
    """DM 전투의 모든 게시물은 최초 [전투 발생] DM의 visibility를 따르고 서로
    답글로 이어지며, 아군 커맨드로 적이 전멸하면 admin의 [진행] 없이 즉시
    전투가 종료되고 state.dm_battles에서 제거되어야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch, enemy_max_hp=1
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )
    pre_call = mastodon.status_post_calls[-1]
    assert pre_call["visibility"] == "direct"
    assert pre_call["in_reply_to_id"] == 1
    dm_state = next(iter(state.dm_battles.values()))
    pre_post_id = dm_state.active_post_id

    # admin 프록시로 적 PRE 선언 (이동만, 대미지 없음)
    listener.on_notification(
        _make_notification("test-admin", 2, pre_post_id, "고블린 [이동/2열]")
    )
    proxy_reply = mastodon.status_post_calls[-1]
    assert "고블린" in name_dict  # sanity
    assert str(dm_state.session.context) in proxy_reply["status"]

    # admin이 [진행]으로 ALLY_ACTION 진입 — 이전 게시물에 답글로 이어져야 함
    listener.on_notification(
        _make_notification("test-admin", 3, pre_post_id, "[진행]")
    )
    ally_call = mastodon.status_post_calls[-1]
    assert ally_call["visibility"] == "direct"
    assert ally_call["in_reply_to_id"] == pre_post_id
    active_post_id = dm_state.active_post_id
    assert active_post_id != pre_post_id

    # 아군이 공격해 적을 전멸시킴 — [진행] 없이 즉시 종료돼야 함
    listener.on_notification(
        _make_notification("player_acct", 4, active_post_id, "[공격/고블린]")
    )

    end_call = mastodon.status_post_calls[-1]
    assert end_call["visibility"] == "direct"
    assert end_call["in_reply_to_id"] == active_post_id
    assert "전투 종료" in end_call["status"]
    assert "아군" in end_call["status"]
    assert state.dm_battles == {}


def test_dm_battle_character_reply_always_includes_field_board(monkeypatch):
    """DM 전투는 실시간 확인 수단이 답글뿐이므로, 아군 커맨드 답글에도 매번
    현재 필드 상태(str(context))가 포함되어야 한다."""
    mastodon, listener, state, char_dict, name_dict = _setup_dm_battle_state(
        monkeypatch, enemy_max_hp=100
    )

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player_acct"],
        )
    )
    dm_state = next(iter(state.dm_battles.values()))
    pre_post_id = dm_state.active_post_id

    listener.on_notification(
        _make_notification("test-admin", 2, pre_post_id, "[진행]")
    )
    active_post_id = dm_state.active_post_id

    listener.on_notification(
        _make_notification("player_acct", 3, active_post_id, "[공격/고블린]")
    )

    char_reply = mastodon.status_post_calls[-1]
    assert str(dm_state.session.context) in char_reply["status"]


def test_dm_battles_run_concurrently_without_state_bleed(monkeypatch):
    """두 개의 DM 전투가 동시에 진행되어도 서로의 상태(적/아군 배치, 라운드)가
    섞이면 안 된다 — state.dm_battles는 여러 인스턴스를 동시에 관리해야 한다."""
    monkeypatch.setattr(log_sheets, "_load_hp_write_targets", lambda spreadsheet, cache=None: {})
    state = _make_state()
    char_dict = {
        "player1_acct": get_test_preset("전사1"),
        "player2_acct": get_test_preset("전사2"),
    }
    name_dict = {
        "전사1": get_test_preset("전사1"),
        "전사2": get_test_preset("전사2"),
        "고블린": get_test_preset("고블린"),
        "오크": get_test_preset("오크"),
    }
    monkeypatch.setattr(
        main_module, "load_char_data", lambda spreadsheet, cache=None: (char_dict, name_dict, {})
    )
    monkeypatch.setattr(
        admin_module,
        "load_battle_data",
        lambda spreadsheet, cache=None: ({}, {}, {}, {}, None, char_dict, name_dict, {}),
    )
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, state, bot_acct="bot")

    listener.on_notification(
        _make_notification(
            "test-admin",
            1,
            0,
            "[전투 발생][배치/고블린/1열]",
            visibility="direct",
            extra_mentions=["player1_acct"],
        )
    )
    listener.on_notification(
        _make_notification(
            "test-admin",
            2,
            0,
            "[전투 발생][배치/오크/2열]",
            visibility="direct",
            extra_mentions=["player2_acct"],
        )
    )

    assert len(state.dm_battles) == 2
    dm_states = list(state.dm_battles.values())
    goblin_battle = next(
        dm for dm in dm_states if CharacterId("고블린") in dm.session.context.characters
    )
    orc_battle = next(
        dm for dm in dm_states if CharacterId("오크") in dm.session.context.characters
    )
    assert goblin_battle is not orc_battle
    assert CharacterId("오크") not in goblin_battle.session.context.characters
    assert CharacterId("고블린") not in orc_battle.session.context.characters
    assert CharacterId("전사1") in goblin_battle.session.context.characters
    assert CharacterId("전사2") in orc_battle.session.context.characters
