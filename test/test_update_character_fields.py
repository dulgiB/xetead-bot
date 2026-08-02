import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import gspread  # noqa: E402

from bot.load_data import (  # noqa: E402
    update_character_curr_hp,
    update_character_gold_and_quest_date,
)
from bot.sheet_cache import SheetCache  # noqa: E402


class _FakeWorksheet:
    def __init__(self, rows: list[list]):
        self.rows = rows  # 헤더 포함, get_values() 형식
        self.written: list[tuple[int, int, object]] = []
        self.get_values_call_count = 0

    def get_values(self, value_render_option=None, pad_values=True):
        self.get_values_call_count += 1
        return self.rows

    def update_cell(self, row, col, value):
        self.written.append((row, col, value))


class _FakeSpreadsheet:
    def __init__(self, sheets: dict[str, list[list]]):
        self._sheets = {name: _FakeWorksheet(rows) for name, rows in sheets.items()}
        self.id = "fake-id"
        self.client = None
        self.fetch_sheet_metadata_call_count = 0

    def worksheet(self, name):
        if name not in self._sheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._sheets[name]

    def fetch_sheet_metadata(self):
        self.fetch_sheet_metadata_call_count += 1
        return {"sheets": [{"properties": {"title": name}} for name in self._sheets]}


def _make_cache(spreadsheet: _FakeSpreadsheet) -> SheetCache:
    return SheetCache(
        spreadsheet,
        worksheet_factory=lambda properties: spreadsheet._sheets[properties["title"]],
    )


def test_update_character_curr_hp_writes_matching_row():
    rows = [["name", "curr_hp"], ["아군1", "50"], ["아군2", "30"]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_curr_hp(spreadsheet, "아군2", 10)

    ws = spreadsheet.worksheet("캐릭터")
    assert (3, 2, 10) in ws.written


def test_update_character_curr_hp_falls_back_to_enemy_sheet():
    char_rows = [["name", "curr_hp"], ["아군1", "50"]]
    enemy_rows = [["name", "curr_hp"], ["고블린", "20"]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": char_rows, "에너미": enemy_rows})

    update_character_curr_hp(spreadsheet, "고블린", 5)

    assert (2, 2, 5) in spreadsheet.worksheet("에너미").written
    assert spreadsheet.worksheet("캐릭터").written == []


def test_update_character_curr_hp_raises_when_not_found():
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name", "curr_hp"], ["아군1", "50"]]})

    try:
        update_character_curr_hp(spreadsheet, "없는캐릭터", 10)
        assert False, "예외가 발생해야 한다"
    except RuntimeError:
        pass


def test_update_character_curr_hp_with_cache_shares_metadata_and_invalidates():
    """cache를 넘기면 "캐릭터"/"에너미" 조회가 메타데이터를 공유해야 하고,
    쓰기 후에는 실제로 쓴 시트의 캐시 값이 무효화되어 다음 읽기가 최신
    값을 다시 읽어와야 한다."""
    char_rows = [["name", "curr_hp"], ["아군1", "50"]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": char_rows})
    cache = _make_cache(spreadsheet)

    update_character_curr_hp(spreadsheet, "아군1", 33, cache=cache)

    assert spreadsheet.fetch_sheet_metadata_call_count == 1
    ws = spreadsheet.worksheet("캐릭터")
    assert (2, 2, 33) in ws.written

    # 쓰기 직후 다시 읽으면(캐시가 무효화됐으므로) 최신 get_values 호출이 발생해야 한다.
    before = ws.get_values_call_count
    cache.get_all_values("캐릭터")
    assert ws.get_values_call_count == before + 1


def test_update_character_gold_and_quest_date_writes_matching_row():
    rows = [
        ["name", "gold", "daily_quest_date"],
        ["아군1", "5", "2026-01-01"],
        ["아군2", "0", ""],
    ]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_gold_and_quest_date(spreadsheet, "아군2", 1, "2026-08-03")

    ws = spreadsheet.worksheet("캐릭터")
    assert (3, 2, 1) in ws.written
    assert (3, 3, "2026-08-03") in ws.written


def test_update_character_gold_and_quest_date_raises_when_not_found():
    spreadsheet = _FakeSpreadsheet(
        {"캐릭터": [["name", "gold", "daily_quest_date"], ["아군1", "0", ""]]}
    )

    try:
        update_character_gold_and_quest_date(spreadsheet, "없는캐릭터", 1, "2026-08-03")
        assert False, "예외가 발생해야 한다"
    except RuntimeError:
        pass
