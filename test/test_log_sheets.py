import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import gspread  # noqa: E402

from battle.core.battlefield_context import BattlefieldContext  # noqa: E402
from battle.core.commands.models import (  # noqa: E402
    BattleLogEntry,
    BattleLogEntryKind,
)
from battle.objects.define import BattlefieldColumnIndex, FactionType  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from bot import log_sheets  # noqa: E402
from bot.sheet_cache import SheetCache  # noqa: E402
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


class _FakeHpWorksheet:
    """ "캐릭터"/"에너미" 시트 하나를 흉내낸다. name→행 매핑이 담긴 원본
    2차원 배열을 들고 있으며, update_cell 호출을 기록한다."""

    def __init__(self, rows: list[list], fail_for: set[str] | None = None):
        self._rows = rows  # 헤더 포함, get_values() 형식
        self._fail_for = fail_for or set()
        self.written: list[tuple[int, int, int]] = []
        self.get_values_call_count = 0

    def get_values(self, value_render_option=None, pad_values=True):
        self.get_values_call_count += 1
        return self._rows

    def update_cell(self, row, col, value):
        name = self._rows[row - 1][0]
        if name in self._fail_for:
            raise RuntimeError("시트 API 실패")
        self.written.append((row, col, value))


class _FakeSpreadsheetForHpLookup:
    """ "캐릭터"/"에너미" 두 시트로 구성된 가짜 스프레드시트. 헤더는
    [name, curr_hp] 고정."""

    def __init__(self, char_names: list[str], enemy_names: list[str] | None = None):
        char_rows = [["name", "curr_hp"]] + [[n, "0"] for n in char_names]
        self._sheets = {"캐릭터": _FakeHpWorksheet(char_rows)}
        if enemy_names is not None:
            enemy_rows = [["name", "curr_hp"]] + [[n, "0"] for n in enemy_names]
            self._sheets["에너미"] = _FakeHpWorksheet(enemy_rows)
        self.worksheet_call_count = 0
        self.fetch_sheet_metadata_call_count = 0

    def worksheet(self, name):
        self.worksheet_call_count += 1
        if name not in self._sheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._sheets[name]

    def fetch_sheet_metadata(self):
        self.fetch_sheet_metadata_call_count += 1
        return {"sheets": [{"properties": {"title": name}} for name in self._sheets]}


def test_write_back_changed_hp_absorbs_failure_and_continues():
    """한 캐릭터의 시트 반영이 실패해도 예외가 위로 전파되면 안 된다 —
    전파되면 이미 끝난 커맨드 처리의 응답 자체가 사라지고, 재시도 시
    같은 행동이 중복 적용되는 문제로 이어진다. 나머지 캐릭터는 정상적으로
    반영되어야 한다."""
    ctx = _make_context_with_two_characters()
    spreadsheet = _FakeSpreadsheetForHpLookup(["아군1", "아군2"])
    spreadsheet.worksheet("캐릭터")._fail_for = {"아군1"}

    entries = [
        BattleLogEntry(
            target_name="아군1",
            kind=BattleLogEntryKind.DAMAGE,
            result="대미지 10",
            value=10,
        ),
        BattleLogEntry(
            target_name="아군2",
            kind=BattleLogEntryKind.DAMAGE,
            result="대미지 5",
            value=5,
        ),
    ]

    # 예외를 던지지 않아야 한다.
    log_sheets.write_back_changed_hp(spreadsheet, ctx, entries)

    ws = spreadsheet.worksheet("캐릭터")
    written_names = {ws._rows[row - 1][0] for row, _, _ in ws.written}
    assert written_names == {"아군2"}
    assert (3, 2, ctx.characters[CharacterId("아군2")].status.curr_hp) in ws.written


def test_write_back_changed_hp_writes_zero_for_eliminated_character():
    """라운드 종료 시 체력 0으로 이미 제거된 캐릭터는 시트에 0으로
    기록되어야 한다(더 이상 context.characters에 없다는 것 자체가
    탈락을 의미한다)."""
    ctx = _make_context_with_two_characters()
    ctx.remove_character(CharacterId("아군1"))
    spreadsheet = _FakeSpreadsheetForHpLookup(["아군1", "아군2"])

    entries = [
        BattleLogEntry(
            target_name="아군1",
            kind=BattleLogEntryKind.DAMAGE,
            result="대미지 100",
            value=100,
        ),
    ]
    log_sheets.write_back_changed_hp(spreadsheet, ctx, entries)

    ws = spreadsheet.worksheet("캐릭터")
    assert (2, 2, 0) in ws.written


def test_write_back_changed_hp_logs_companion_miss_at_debug_not_error(caplog):
    """소환된 동료는 애초에 "캐릭터"/"에너미" 시트에 자기 행이 없어 시트
    반영을 건너뛰는 게 정상 동작이다 — 실제 문제가 있는 캐릭터 누락과
    달리 ERROR가 아니라 DEBUG로만 남아야 한다."""
    import logging

    ctx = _make_context_with_two_characters()
    ctx.add_character(
        get_test_preset("동료"), FactionType.ALLY, BattlefieldColumnIndex(2)
    )
    ctx.companion_owners[CharacterId("동료")] = CharacterId("아군1")
    spreadsheet = _FakeSpreadsheetForHpLookup(["아군1", "아군2"])  # "동료" 행 없음

    entries = [
        BattleLogEntry(
            target_name="동료",
            kind=BattleLogEntryKind.DAMAGE,
            result="대미지 5",
            value=5,
        ),
    ]

    with caplog.at_level(logging.DEBUG, logger="bot.log_sheets"):
        log_sheets.write_back_changed_hp(spreadsheet, ctx, entries)

    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
    assert any(
        r.levelno == logging.DEBUG and "동료" in r.getMessage() for r in caplog.records
    )


def test_write_back_changed_hp_still_logs_error_for_non_companion_miss(caplog):
    """소환된 동료가 아닌 일반 캐릭터가 시트에서 안 찾아지는 건 여전히 실제
    문제이므로 ERROR로 남아야 한다(위 동료 케이스와 구분)."""
    import logging

    ctx = _make_context_with_two_characters()
    spreadsheet = _FakeSpreadsheetForHpLookup(["아군1"])  # "아군2" 행 없음

    entries = [
        BattleLogEntry(
            target_name="아군2",
            kind=BattleLogEntryKind.DAMAGE,
            result="대미지 5",
            value=5,
        ),
    ]

    with caplog.at_level(logging.DEBUG, logger="bot.log_sheets"):
        log_sheets.write_back_changed_hp(spreadsheet, ctx, entries)

    assert any(
        r.levelno == logging.ERROR and "아군2" in r.getMessage() for r in caplog.records
    )


def test_load_hp_write_targets_reads_each_sheet_only_once():
    """바뀐 캐릭터가 여러 명이어도 시트 읽기는 시트당 1회로 고정되어야 한다."""
    spreadsheet = _FakeSpreadsheetForHpLookup(
        ["아군1", "아군2", "아군3"], enemy_names=["적1", "적2"]
    )

    targets = log_sheets._load_hp_write_targets(spreadsheet)

    assert set(targets.keys()) == {"아군1", "아군2", "아군3", "적1", "적2"}
    assert spreadsheet.worksheet("캐릭터").get_values_call_count == 1
    assert spreadsheet.worksheet("에너미").get_values_call_count == 1


def test_write_back_changed_hp_reuses_given_cache():
    """SheetCache를 넘기면, 이미 그 캐시에 읽혀 있는 값을 재사용해 추가
    네트워크 호출 없이 write-back 대상을 찾아야 한다(reload_char_data가
    이미 "캐릭터"/"에너미"를 UNFORMATTED로 읽어 둔 뒤라고 가정)."""
    ctx = _make_context_with_two_characters()
    spreadsheet = _FakeSpreadsheetForHpLookup(["아군1", "아군2"])
    cache = SheetCache(
        spreadsheet,
        worksheet_factory=lambda properties: spreadsheet.worksheet(properties["title"]),
    )
    # load_char_data()가 커맨드 처리 초반에 이미 채워 뒀을 캐시를 흉내낸다.
    cache.get_all_records("캐릭터", value_render_option=log_sheets._UNFORMATTED)

    entries = [
        BattleLogEntry(
            target_name="아군1",
            kind=BattleLogEntryKind.DAMAGE,
            result="대미지 10",
            value=10,
        ),
    ]
    log_sheets.write_back_changed_hp(spreadsheet, ctx, entries, cache=cache)

    # get_all_records 호출 시점에 이미 get_values가 1회 불렸으므로, 그 이후
    # write_back_changed_hp가 같은 캐시 키로 다시 조회해도 추가 호출이 없어야 한다.
    assert spreadsheet.worksheet("캐릭터").get_values_call_count == 1


class _FakeFieldWorksheet:
    def __init__(self):
        self.rows = [
            [
                "id",
                "battle_type",
                "started_at",
                "ended_at",
                "round",
                "phase",
                "characters_json",
                "meta_json",
            ]
        ]
        self.get_all_values_call_count = 0

    def get_all_values(self):
        self.get_all_values_call_count += 1
        return self.rows

    def get_values(self, value_render_option=None, pad_values=True):
        self.get_all_values_call_count += 1
        return self.rows

    def update(self, values, range_name=None, value_input_option=None):
        # "A2:H2" 형식에서 행 번호만 뽑아 그 행을 갱신한다.
        row_idx = int(range_name[1:].split(":")[0])
        self.rows[row_idx - 1] = values[0]

    def update_cell(self, row, col, value):
        row_list = self.rows[row - 1]
        row_list += [""] * (col - len(row_list))
        row_list[col - 1] = value

    def insert_rows(self, values, row, value_input_option=None):
        self.rows.insert(row - 1, values[0])


class _FakeFieldSpreadsheet:
    def __init__(self, ws):
        self._ws = ws
        self.id = "fake-field-spreadsheet-id"
        self.client = None

    def fetch_sheet_metadata(self):
        return {"sheets": [{"properties": {"title": "필드"}}]}

    def worksheet(self, name):
        return self._ws


def test_upsert_field_row_invalidates_cache_after_write():
    """캐시를 넘겨 upsert_field_row를 두 번 연속 호출하면(같은 커맨드 처리
    중 여러 페이즈를 한 번에 반영하는 경우 등), 두 번째 호출이 첫 번째
    호출이 방금 쓴 내용을 못 보고 새 행을 중복 삽입하면 안 된다."""
    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)
    cache = SheetCache(spreadsheet, worksheet_factory=lambda properties: ws)

    log_sheets.upsert_field_row(
        spreadsheet,
        "field-1",
        battle_type=log_sheets.FieldBattleType.MAIN,
        round_n=1,
        phase="ALLY_ACTION",
        characters=[],
        cache=cache,
    )
    log_sheets.upsert_field_row(
        spreadsheet,
        "field-1",
        battle_type=log_sheets.FieldBattleType.MAIN,
        round_n=2,
        phase="ENEMY_POST_ACTION",
        characters=[],
        cache=cache,
    )

    # 두 번째 호출이 첫 번째가 삽입한 행을 찾아 갱신했어야 한다 — 새 행이
    # 하나 더 생기면 안 된다(헤더 + 데이터 행 1개 = 총 2행).
    assert len(ws.rows) == 2
    assert ws.rows[1][4] == 2  # round 컬럼이 마지막 값(2)으로 갱신됨
    assert ws.rows[1][1] == "본전투"


def test_upsert_field_row_single_slot_fallback_ignores_dm():
    """DM 전투는 동시에 여러 개 진행될 수 있으므로, field_id가 다르면
    (같은 battle_type이어도) 기존 행을 재사용하지 않고 새 행을 삽입해야
    한다 — MAIN만 "동시 1개 슬롯" fallback 대상이다."""
    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)

    log_sheets.upsert_field_row(
        spreadsheet,
        "dm-1",
        battle_type=log_sheets.FieldBattleType.DM,
        round_n=1,
        phase="ENEMY_PRE_ACTION",
        characters=[],
    )
    log_sheets.upsert_field_row(
        spreadsheet,
        "dm-2",
        battle_type=log_sheets.FieldBattleType.DM,
        round_n=1,
        phase="ENEMY_PRE_ACTION",
        characters=[],
    )

    assert len(ws.rows) == 3  # 헤더 + DM 전투 2건
    assert {row[0] for row in ws.rows[1:]} == {"dm-1", "dm-2"}


def test_upsert_field_row_single_slot_fallback_ignores_practice():
    """대련/상시전투도 DM 전투처럼 동시에 여러 개 진행될 수 있으므로,
    field_id가 다르면 기존 행을 재사용하지 않고 새 행을 삽입해야 한다 —
    재사용하면 동시 진행 중인 다른 대련/상시전투의 행을 엉뚱하게 덮어써
    그 세션이 "필드" 시트에서 통째로 사라진다."""
    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)

    log_sheets.upsert_field_row(
        spreadsheet,
        "prep-1",
        battle_type=log_sheets.FieldBattleType.PRACTICE,
        round_n=1,
        phase="FIRST_MOVER_ACTION",
        characters=[],
    )
    log_sheets.upsert_field_row(
        spreadsheet,
        "prep-2",
        battle_type=log_sheets.FieldBattleType.PRACTICE,
        round_n=1,
        phase="FIRST_MOVER_ACTION",
        characters=[],
    )

    assert len(ws.rows) == 3  # 헤더 + 대련 2건
    assert {row[0] for row in ws.rows[1:]} == {"prep-1", "prep-2"}


def test_upsert_field_row_single_slot_fallback_reuses_row_for_main():
    """MAIN은 동시에 1개만 진행된다는 전제 하에, field_id가 바뀌어도 같은
    battle_type의 가장 최근 행을 재사용해야 한다."""
    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)

    log_sheets.upsert_field_row(
        spreadsheet,
        "main-1",
        battle_type=log_sheets.FieldBattleType.MAIN,
        round_n=1,
        phase="ENEMY_PRE_ACTION",
        characters=[],
    )
    log_sheets.upsert_field_row(
        spreadsheet,
        "main-2",
        battle_type=log_sheets.FieldBattleType.MAIN,
        round_n=2,
        phase="ALLY_ACTION",
        characters=[],
    )

    assert len(ws.rows) == 2  # 새 행이 추가되지 않고 기존 행이 갱신됨
    assert ws.rows[1][0] == "main-2"
    assert ws.rows[1][4] == 2


def test_upsert_field_row_meta_json_round_trip():
    """meta에 넘긴 dict가 meta_json 컬럼에 그대로 직렬화되어야 한다."""
    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)

    log_sheets.upsert_field_row(
        spreadsheet,
        "field-1",
        battle_type=log_sheets.FieldBattleType.MAIN,
        round_n=1,
        phase="ALLY_ACTION",
        characters=[],
        meta={"name": "테스트 전투", "active_phase_post_id": 123},
    )

    import json

    assert json.loads(ws.rows[1][7]) == {
        "name": "테스트 전투",
        "active_phase_post_id": 123,
    }


def test_update_field_meta_merges_into_existing_meta():
    """update_field_meta는 기존 meta_json의 다른 키는 보존하고 넘긴 키만
    덮어써야 한다."""
    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)

    log_sheets.upsert_field_row(
        spreadsheet,
        "field-1",
        battle_type=log_sheets.FieldBattleType.MAIN,
        round_n=1,
        phase="ENEMY_PRE_ACTION",
        characters=[],
        meta={"name": "테스트 전투"},
    )
    log_sheets.update_field_meta(spreadsheet, "field-1", {"active_phase_post_id": 999})

    import json

    assert json.loads(ws.rows[1][7]) == {
        "name": "테스트 전투",
        "active_phase_post_id": 999,
    }


def test_update_field_meta_skips_when_row_missing(caplog):
    """아직 upsert_field_row가 호출되지 않아 행 자체가 없으면 조용히
    건너뛰어야 한다(예외를 던지면 안 된다)."""
    import logging

    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)

    with caplog.at_level(logging.WARNING, logger="bot.log_sheets"):
        log_sheets.update_field_meta(spreadsheet, "no-such-id", {"x": 1})

    assert len(ws.rows) == 1  # 헤더만 존재
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_now_format_has_no_iso_t_or_timezone_suffix():
    """Google Sheets USER_ENTERED는 ISO 8601의 'T' 구분자·타임존 접미사가
    있으면 날짜로 파싱하지 못한다 — 공백 구분 포맷이어야 한다."""
    import re

    value = log_sheets._now()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value)


def test_build_field_characters_includes_faction():
    """복원 시 진영을 알아야 add_character(faction=...)를 다시 호출할 수
    있으므로, faction이 스냅샷에 포함되어야 한다."""
    ctx = _make_context_with_two_characters()
    rows = log_sheets.build_field_characters(ctx, include_hp=False)
    assert all(row["faction"] == "아군" for row in rows)
    assert {row["name"] for row in rows} == {"아군1", "아군2"}


def test_load_open_battle_rows_excludes_ended_and_parses_fields():
    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)

    log_sheets.upsert_field_row(
        spreadsheet,
        "open-1",
        battle_type=log_sheets.FieldBattleType.MAIN,
        round_n=2,
        phase="ALLY_ACTION",
        characters=[
            {"name": "아군1", "faction": "아군", "position": 1, "remaining_cost": 3}
        ],
        meta={"name": "진행중 전투"},
    )
    log_sheets.upsert_field_row(
        spreadsheet,
        "dm-ended",
        battle_type=log_sheets.FieldBattleType.DM,
        round_n=5,
        phase="BUFF_UPDATE_AND_NEXT_ROUND_STANDBY",
        characters=[],
        ended=True,
    )

    rows = log_sheets.load_open_battle_rows(spreadsheet)

    assert [r.field_id for r in rows] == ["open-1"]
    row = rows[0]
    assert row.battle_type == log_sheets.FieldBattleType.MAIN
    assert row.round_n == 2
    assert row.phase == "ALLY_ACTION"
    assert row.characters == [
        {"name": "아군1", "faction": "아군", "position": 1, "remaining_cost": 3}
    ]
    assert row.meta == {"name": "진행중 전투"}


def test_field_sheet_name_configurable_via_env(monkeypatch):
    """bot_test와 bot(운영)이 DB_SPREADSHEET_KEY를 공유하므로, 크래시 복구용
    "필드" 워크시트 이름을 고정하면 테스트 본전투가 운영 전투 행을 upsert로
    덮어쓴다. FIELD_LOG_SHEET_NAME으로 배포별 워크시트를 분리할 수 있어야
    하고, 설정하지 않으면 기존과 동일하게 "필드"를 써야 한다."""
    import importlib

    monkeypatch.setenv("FIELD_LOG_SHEET_NAME", "필드_테스트")
    importlib.reload(log_sheets)
    try:
        assert log_sheets._FIELD_SHEET == "필드_테스트"
    finally:
        monkeypatch.delenv("FIELD_LOG_SHEET_NAME", raising=False)
        importlib.reload(log_sheets)
    assert log_sheets._FIELD_SHEET == "필드"


def test_battle_log_sheet_names_use_test_prefix_for_test_instance(monkeypatch):
    """운영과 테스트가 LOG_SPREADSHEET_KEY(같은 스프레드시트)를 공유하므로,
    MASTODON_API_BASE_URL 호스트가 test.xetead.quest일 때는 "테스트_" 접두사
    워크시트로, 그 외(운영)에는 접두사 없는 워크시트로 분리되어야 한다."""
    import importlib

    monkeypatch.setenv("MASTODON_API_BASE_URL", "https://test.xetead.quest")
    importlib.reload(log_sheets)
    try:
        assert log_sheets._BATTLE_LOG_SHEET == "테스트_로그_전투"
        assert log_sheets._NONCOMBAT_LOG_SHEET == "테스트_로그_비전투"
    finally:
        monkeypatch.delenv("MASTODON_API_BASE_URL", raising=False)
        importlib.reload(log_sheets)
    assert log_sheets._BATTLE_LOG_SHEET == "로그_전투"
    assert log_sheets._NONCOMBAT_LOG_SHEET == "로그_비전투"


class _FakeLedgerWorksheet:
    def __init__(self, rows: list[list], row_count: int | None = None):
        self.rows = rows  # 헤더 포함
        self.row_count = row_count if row_count is not None else len(rows)
        self.appended: list[list] = []

    def get_all_values(self):
        return self.rows

    def get_values(self, value_render_option=None, pad_values=True):
        return self.rows

    def update(self, values, range_name=None, value_input_option=None):
        row_idx = int(range_name[1:].split(":")[0])
        while len(self.rows) < row_idx:
            self.rows.append([])
        self.rows[row_idx - 1] = values[0]

    def append_row(self, values, value_input_option=None):
        self.rows.append(values)
        self.appended.append(values)


class _FakeLedgerSpreadsheet:
    def __init__(self, ws):
        self._ws = ws

    def worksheet(self, name):
        return self._ws


def test_append_ledger_row_fills_first_blank_row_instead_of_appending_past_it():
    """서식/구획용으로 미리 만들어 둔 빈 행이 데이터 아래에 있으면, 기본
    append_row(Sheets API values.append)는 그 빈 행을 건너뛰고 시트 맨
    아래까지 내려가 버린다 — 데이터 바로 다음(첫 빈 행)에 써야 한다."""
    ws = _FakeLedgerWorksheet(
        rows=[
            ["날짜", "캐릭터", "변동 사유", "금액"],
            ["2026-08-01", "아군1", "일일 의뢰", 1],
        ],
        row_count=10,  # 아래에 버퍼용 빈 행이 더 있음
    )
    spreadsheet = _FakeLedgerSpreadsheet(ws)

    log_sheets.append_ledger_row(spreadsheet, "2026-08-20", "아군2", "일일 의뢰", 1)

    assert ws.appended == []
    assert ws.rows[2] == ["2026-08-20", "아군2", "일일 의뢰", 1]
    assert len(ws.rows) == 3


def test_append_ledger_row_ignores_array_formula_spillover_columns():
    """실제 "가계부" 시트의 E~G열("누적 +"/"누적 -"/"최종")은 B열을 통째로
    훑는 배열 수식(MAP(B2:B, ...))이라, 그 수식이 훑는 행 수가 늘어나면
    A~D열이 비어 있는 행도 E~G열엔 빈 문자열이 스필돼 채워진다 — 이런 행을
    "값이 있는 행"으로 오인해 건너뛰면 안 되고, A열(날짜) 기준으로 첫 빈
    행을 찾아야 한다."""
    ws = _FakeLedgerWorksheet(
        rows=[
            ["날짜", "캐릭터", "변동 사유", "금액", "누적 +", "누적 -", "최종"],
            ["2026-08-01", "아군1", "일일 의뢰", 1, 1, "", 1],
            # 서식/구획용 빈 행 — A~D는 비어 있지만 배열 수식 스필로 E~G에
            # 빈 문자열이 들어가 있다.
            ["", "", "", "", "", "", ""],
        ],
        row_count=5,
    )
    spreadsheet = _FakeLedgerSpreadsheet(ws)

    log_sheets.append_ledger_row(spreadsheet, "2026-08-20", "아군2", "일일 의뢰", 1)

    assert ws.appended == []
    assert ws.rows[2] == ["2026-08-20", "아군2", "일일 의뢰", 1]
    assert len(ws.rows) == 3


def test_append_ledger_row_inserts_new_row_when_sheet_is_full():
    """미리 만들어 둔 빈 행이 없어 시트가 꽉 차 있으면 새 행을 삽입해야
    한다."""
    ws = _FakeLedgerWorksheet(
        rows=[
            ["날짜", "캐릭터", "변동 사유", "금액"],
            ["2026-08-01", "아군1", "일일 의뢰", 1],
        ],
        row_count=2,  # 여유 행 없음
    )
    spreadsheet = _FakeLedgerSpreadsheet(ws)

    log_sheets.append_ledger_row(spreadsheet, "2026-08-20", "아군2", "일일 의뢰", 1)

    assert ws.appended == [["2026-08-20", "아군2", "일일 의뢰", 1]]


def test_battle_log_sheet_names_default_for_prod_instance(monkeypatch):
    import importlib

    monkeypatch.setenv("MASTODON_API_BASE_URL", "https://xetead.quest")
    importlib.reload(log_sheets)
    try:
        assert log_sheets._BATTLE_LOG_SHEET == "로그_전투"
        assert log_sheets._NONCOMBAT_LOG_SHEET == "로그_비전투"
    finally:
        monkeypatch.delenv("MASTODON_API_BASE_URL", raising=False)
        importlib.reload(log_sheets)
