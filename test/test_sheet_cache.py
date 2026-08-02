import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import gspread  # noqa: E402

from bot.sheet_cache import SheetCache  # noqa: E402


class _FakeWorksheet:
    def __init__(self, rows: list[list]):
        self._rows = rows
        self.get_values_call_count = 0

    def get_values(self, value_render_option=None, pad_values=True):
        self.get_values_call_count += 1
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, sheets: dict[str, list[list]]):
        self._worksheets = {name: _FakeWorksheet(rows) for name, rows in sheets.items()}
        self.worksheet_call_count = 0

    def worksheet(self, name):
        self.worksheet_call_count += 1
        if name not in self._worksheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._worksheets[name]


def test_get_all_values_caches_after_first_read():
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name", "curr_hp"], ["아군1", "50"]]})
    ws = spreadsheet.worksheet("캐릭터")
    spreadsheet.worksheet_call_count = 0  # 위 조회는 테스트 셋업이라 제외

    cache = SheetCache(spreadsheet)
    first = cache.get_all_values("캐릭터")
    second = cache.get_all_values("캐릭터")

    assert first == second == [["name", "curr_hp"], ["아군1", "50"]]
    assert ws.get_values_call_count == 1
    assert spreadsheet.worksheet_call_count == 1


def test_different_value_render_option_is_a_separate_cache_key():
    """get_all_records(value_render_option=UNFORMATTED)와 get_all_values()(기본
    옵션)는 서로 다른 렌더링 결과를 낼 수 있으므로 같은 캐시 엔트리를
    공유하면 안 된다."""
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name"], ["아군1"]]})
    cache = SheetCache(spreadsheet)

    cache.get_all_values("캐릭터", value_render_option="FORMATTED_VALUE")
    cache.get_all_values("캐릭터", value_render_option="UNFORMATTED_VALUE")

    assert spreadsheet.worksheet("캐릭터").get_values_call_count == 2


def test_get_all_records_numericises_like_gspread():
    spreadsheet = _FakeSpreadsheet(
        {"캐릭터": [["name", "curr_hp"], ["아군1", "50"], ["아군2", "30"]]}
    )
    cache = SheetCache(spreadsheet)

    records = cache.get_all_records("캐릭터")

    assert records == [
        {"name": "아군1", "curr_hp": 50},
        {"name": "아군2", "curr_hp": 30},
    ]


def test_get_all_records_reuses_get_all_values_cache():
    spreadsheet = _FakeSpreadsheet(
        {"캐릭터": [["name", "curr_hp"], ["아군1", "50"]]}
    )
    cache = SheetCache(spreadsheet)

    cache.get_all_values("캐릭터")
    cache.get_all_records("캐릭터")

    assert spreadsheet.worksheet("캐릭터").get_values_call_count == 1


def test_invalidate_clears_only_that_sheet():
    spreadsheet = _FakeSpreadsheet(
        {
            "캐릭터": [["name"], ["아군1"]],
            "에너미": [["name"], ["적1"]],
        }
    )
    cache = SheetCache(spreadsheet)
    cache.get_all_values("캐릭터")
    cache.get_all_values("에너미")

    cache.invalidate("캐릭터")
    cache.get_all_values("캐릭터")
    cache.get_all_values("에너미")

    assert spreadsheet.worksheet("캐릭터").get_values_call_count == 2
    assert spreadsheet.worksheet("에너미").get_values_call_count == 1
