import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

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
    """"캐릭터"/"에너미" 시트 하나를 흉내낸다. name→행 매핑이 담긴 원본
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
    """"캐릭터"/"에너미" 두 시트로 구성된 가짜 스프레드시트. 헤더는
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
            target_name="아군1", kind=BattleLogEntryKind.DAMAGE, result="대미지 10", value=10
        ),
        BattleLogEntry(
            target_name="아군2", kind=BattleLogEntryKind.DAMAGE, result="대미지 5", value=5
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
        worksheet_factory=lambda properties: spreadsheet.worksheet(
            properties["title"]
        ),
    )
    # load_char_data()가 커맨드 처리 초반에 이미 채워 뒀을 캐시를 흉내낸다.
    cache.get_all_records("캐릭터", value_render_option=log_sheets._UNFORMATTED)

    entries = [
        BattleLogEntry(
            target_name="아군1", kind=BattleLogEntryKind.DAMAGE, result="대미지 10", value=10
        ),
    ]
    log_sheets.write_back_changed_hp(spreadsheet, ctx, entries, cache=cache)

    # get_all_records 호출 시점에 이미 get_values가 1회 불렸으므로, 그 이후
    # write_back_changed_hp가 같은 캐시 키로 다시 조회해도 추가 호출이 없어야 한다.
    assert spreadsheet.worksheet("캐릭터").get_values_call_count == 1


def test_upsert_field_row_invalidates_cache_after_write():
    """캐시를 넘겨 upsert_field_row를 두 번 연속 호출하면(같은 커맨드 처리
    중 여러 페이즈를 한 번에 반영하는 경우 등), 두 번째 호출이 첫 번째
    호출이 방금 쓴 내용을 못 보고 새 행을 중복 삽입하면 안 된다."""

    class _FakeFieldWorksheet:
        def __init__(self):
            self.rows = [
                ["id", "is_main", "started_at", "ended_at", "round", "phase", "characters_json"]
            ]
            self.get_all_values_call_count = 0

        def get_all_values(self):
            self.get_all_values_call_count += 1
            return self.rows

        def get_values(self, value_render_option=None, pad_values=True):
            self.get_all_values_call_count += 1
            return self.rows

        def update(self, range_name, values, value_input_option=None):
            # "A2:G2" 형식에서 행 번호만 뽑아 그 행을 갱신한다.
            row_idx = int(range_name[1:].split(":")[0])
            self.rows[row_idx - 1] = values[0]

        def insert_rows(self, values, row, value_input_option=None):
            self.rows.insert(row - 1, values[0])

    class _FakeFieldSpreadsheet:
        def __init__(self, ws):
            self._ws = ws
            self.id = "fake-field-spreadsheet-id"
            self.client = None

        def fetch_sheet_metadata(self):
            return {"sheets": [{"properties": {"title": "필드"}}]}

    ws = _FakeFieldWorksheet()
    spreadsheet = _FakeFieldSpreadsheet(ws)
    cache = SheetCache(spreadsheet, worksheet_factory=lambda properties: ws)

    log_sheets.upsert_field_row(
        spreadsheet, "field-1", is_main=True, round_n=1, phase="ALLY_ACTION",
        characters=[], cache=cache,
    )
    log_sheets.upsert_field_row(
        spreadsheet, "field-1", is_main=True, round_n=2, phase="ENEMY_POST_ACTION",
        characters=[], cache=cache,
    )

    # 두 번째 호출이 첫 번째가 삽입한 행을 찾아 갱신했어야 한다 — 새 행이
    # 하나 더 생기면 안 된다(헤더 + 데이터 행 1개 = 총 2행).
    assert len(ws.rows) == 2
    assert ws.rows[1][4] == 2  # round 컬럼이 마지막 값(2)으로 갱신됨
