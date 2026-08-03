import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

from battle.core.battlefield_context import BattlefieldContext  # noqa: E402
from battle.core.commands.models import (  # noqa: E402
    BattleLogEntry,
    BattleLogEntryKind,
)
from battle.objects.define import BattlefieldColumnIndex, FactionType  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from bot import log_sheets  # noqa: E402
from helpers import get_test_preset  # noqa: E402


def _make_context_with_two_characters() -> BattlefieldContext:
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("아군1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군2"), FactionType.ALLY, BattlefieldColumnIndex(1)
    )
    return ctx


def test_write_back_changed_hp_absorbs_failure_and_continues(monkeypatch):
    """한 캐릭터의 시트 반영이 실패해도 예외가 위로 전파되면 안 된다 —
    전파되면 이미 끝난 커맨드 처리의 응답 자체가 사라지고, 재시도 시
    같은 행동이 중복 적용되는 문제로 이어진다. 나머지 캐릭터는 정상적으로
    반영되어야 한다."""
    ctx = _make_context_with_two_characters()
    written = []

    def _fake_update(spreadsheet, name, curr_hp):
        if name == "아군1":
            raise RuntimeError("시트 API 실패")
        written.append((name, curr_hp))

    monkeypatch.setattr(log_sheets, "update_character_curr_hp", _fake_update)

    entries = [
        BattleLogEntry(
            target_name="아군1", kind=BattleLogEntryKind.DAMAGE, result="대미지 10", value=10
        ),
        BattleLogEntry(
            target_name="아군2", kind=BattleLogEntryKind.DAMAGE, result="대미지 5", value=5
        ),
    ]

    # 예외를 던지지 않아야 한다.
    log_sheets.write_back_changed_hp(None, ctx, entries)

    assert written == [
        ("아군2", ctx.characters[CharacterId("아군2")].status.curr_hp)
    ]


def test_write_back_changed_hp_writes_zero_for_eliminated_character(monkeypatch):
    """라운드 종료 시 체력 0으로 이미 제거된 캐릭터는 시트에 0으로
    기록되어야 한다(더 이상 context.characters에 없다는 것 자체가
    탈락을 의미한다)."""
    ctx = _make_context_with_two_characters()
    written = []
    monkeypatch.setattr(
        log_sheets,
        "update_character_curr_hp",
        lambda spreadsheet, name, curr_hp: written.append((name, curr_hp)),
    )
    ctx.remove_character(CharacterId("아군1"))

    entries = [
        BattleLogEntry(
            target_name="아군1",
            kind=BattleLogEntryKind.DAMAGE,
            result="대미지 100",
            value=100,
        ),
    ]
    log_sheets.write_back_changed_hp(None, ctx, entries)

    assert written == [("아군1", 0)]


def test_write_back_changed_hp_logs_companion_miss_at_debug_not_error(
    monkeypatch, caplog
):
    """소환된 동료는 애초에 "캐릭터"/"에너미" 시트에 자기 행이 없어 시트
    반영을 건너뛰는 게 정상 동작이다 — 실제 문제가 있는 캐릭터 누락과
    달리 ERROR가 아니라 DEBUG로만 남아야 한다."""
    import logging

    ctx = _make_context_with_two_characters()
    ctx.add_character(
        get_test_preset("동료"), FactionType.ALLY, BattlefieldColumnIndex(2)
    )
    ctx.companion_owners[CharacterId("동료")] = CharacterId("아군1")

    def _fake_update(spreadsheet, name, curr_hp):
        raise RuntimeError(f"캐릭터 '{name}'을 캐릭터/에너미 시트에서 찾을 수 없습니다.")

    monkeypatch.setattr(log_sheets, "update_character_curr_hp", _fake_update)

    entries = [
        BattleLogEntry(
            target_name="동료", kind=BattleLogEntryKind.DAMAGE, result="대미지 5", value=5
        ),
    ]

    with caplog.at_level(logging.DEBUG, logger="bot.log_sheets"):
        log_sheets.write_back_changed_hp(None, ctx, entries)

    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
    assert any(
        r.levelno == logging.DEBUG and "동료" in r.getMessage()
        for r in caplog.records
    )


def test_write_back_changed_hp_still_logs_error_for_non_companion_miss(
    monkeypatch, caplog
):
    """소환된 동료가 아닌 일반 캐릭터가 시트에서 안 찾아지는 건 여전히 실제
    문제이므로 ERROR로 남아야 한다(위 동료 케이스와 구분)."""
    import logging

    ctx = _make_context_with_two_characters()

    def _fake_update(spreadsheet, name, curr_hp):
        raise RuntimeError(f"캐릭터 '{name}'을 캐릭터/에너미 시트에서 찾을 수 없습니다.")

    monkeypatch.setattr(log_sheets, "update_character_curr_hp", _fake_update)

    entries = [
        BattleLogEntry(
            target_name="아군2", kind=BattleLogEntryKind.DAMAGE, result="대미지 5", value=5
        ),
    ]

    with caplog.at_level(logging.DEBUG, logger="bot.log_sheets"):
        log_sheets.write_back_changed_hp(None, ctx, entries)

    assert any(
        r.levelno == logging.ERROR and "아군2" in r.getMessage()
        for r in caplog.records
    )
