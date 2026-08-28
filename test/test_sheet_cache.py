import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

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
    """실제 gspread.Spreadsheet과 달리, 이름이 다른 시트를 조회해도
    fetch_sheet_metadata()가 한 번만 불리는지를 검증하기 위한 이중."""

    def __init__(self, sheets: dict[str, list[list]]):
        self._worksheets = {name: _FakeWorksheet(rows) for name, rows in sheets.items()}
        self.id = "fake-spreadsheet-id"
        self.client = None
        self.fetch_sheet_metadata_call_count = 0

    def fetch_sheet_metadata(self):
        self.fetch_sheet_metadata_call_count += 1
        return {
            "sheets": [{"properties": {"title": name}} for name in self._worksheets]
        }


def _make_cache(spreadsheet: _FakeSpreadsheet) -> SheetCache:
    return SheetCache(
        spreadsheet,
        worksheet_factory=lambda properties: spreadsheet._worksheets[
            properties["title"]
        ],
    )


def test_get_all_values_caches_after_first_read():
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name", "curr_hp"], ["아군1", "50"]]})
    ws = spreadsheet._worksheets["캐릭터"]

    cache = _make_cache(spreadsheet)
    first = cache.get_all_values("캐릭터")
    second = cache.get_all_values("캐릭터")

    assert first == second == [["name", "curr_hp"], ["아군1", "50"]]
    assert ws.get_values_call_count == 1
    assert spreadsheet.fetch_sheet_metadata_call_count == 1


def test_worksheet_metadata_fetched_only_once_across_different_names():
    """이름이 다른 시트를 여러 개 조회해도 fetch_sheet_metadata()는 인스턴스당
    한 번만 불려야 한다 — gspread.Spreadsheet.worksheet()가 이름과 무관하게
    매번 전체 메타데이터를 새로 읽어오는 낭비를 없애는 것이 이 캐시의 핵심."""
    spreadsheet = _FakeSpreadsheet(
        {"캐릭터": [["name"], ["아군1"]], "에너미": [["name"], ["적1"]]}
    )
    cache = _make_cache(spreadsheet)

    cache.worksheet("캐릭터")
    cache.worksheet("에너미")
    cache.worksheet("캐릭터")

    assert spreadsheet.fetch_sheet_metadata_call_count == 1


def test_worksheet_raises_not_found_for_unknown_name():
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name"], ["아군1"]]})
    cache = _make_cache(spreadsheet)

    try:
        cache.worksheet("없는시트")
        assert False, "예외가 발생해야 한다"
    except gspread.exceptions.WorksheetNotFound:
        pass


def test_different_value_render_option_is_a_separate_cache_key():
    """get_all_records(value_render_option=UNFORMATTED)와 get_all_values()(기본
    옵션)는 서로 다른 렌더링 결과를 낼 수 있으므로 같은 캐시 엔트리를
    공유하면 안 된다."""
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name"], ["아군1"]]})
    cache = _make_cache(spreadsheet)

    cache.get_all_values("캐릭터", value_render_option="FORMATTED_VALUE")
    cache.get_all_values("캐릭터", value_render_option="UNFORMATTED_VALUE")

    assert spreadsheet._worksheets["캐릭터"].get_values_call_count == 2


def test_get_all_records_numericises_like_gspread():
    spreadsheet = _FakeSpreadsheet(
        {"캐릭터": [["name", "curr_hp"], ["아군1", "50"], ["아군2", "30"]]}
    )
    cache = _make_cache(spreadsheet)

    records = cache.get_all_records("캐릭터")

    assert records == [
        {"name": "아군1", "curr_hp": 50},
        {"name": "아군2", "curr_hp": 30},
    ]


def test_get_all_records_reuses_get_all_values_cache():
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name", "curr_hp"], ["아군1", "50"]]})
    cache = _make_cache(spreadsheet)

    cache.get_all_values("캐릭터")
    cache.get_all_records("캐릭터")

    assert spreadsheet._worksheets["캐릭터"].get_values_call_count == 1


def test_invalidate_clears_only_that_sheet():
    spreadsheet = _FakeSpreadsheet(
        {
            "캐릭터": [["name"], ["아군1"]],
            "에너미": [["name"], ["적1"]],
        }
    )
    cache = _make_cache(spreadsheet)
    cache.get_all_values("캐릭터")
    cache.get_all_values("에너미")

    cache.invalidate("캐릭터")
    cache.get_all_values("캐릭터")
    cache.get_all_values("에너미")

    assert spreadsheet._worksheets["캐릭터"].get_values_call_count == 2
    assert spreadsheet._worksheets["에너미"].get_values_call_count == 1
