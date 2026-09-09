import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import gspread  # noqa: E402

from bot.sheet_cache import SheetCache  # noqa: E402


class _FakeWorksheet:
    def __init__(self, rows: list[list]):
        self._rows = rows
        self.get_values_call_count = 0
        # 재시도 테스트에서 직접 덮어써 실패 횟수/상태 코드를 지정한다
        # (_FakeSpreadsheet가 워크시트를 내부에서 만들어 생성자로는 못 넘김).
        self._remaining_failures = 0
        self._fail_status = 503

    def get_values(self, value_render_option=None, pad_values=True):
        self.get_values_call_count += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise _make_api_error(self._fail_status)
        return self._rows


class _FakeSpreadsheet:
    """실제 gspread.Spreadsheet과 달리, 이름이 다른 시트를 조회해도
    fetch_sheet_metadata()가 한 번만 불리는지를 검증하기 위한 이중."""

    def __init__(
        self,
        sheets: dict[str, list[list]],
        *,
        metadata_fail_times: int = 0,
        metadata_fail_status: int = 503,
    ):
        self._worksheets = {name: _FakeWorksheet(rows) for name, rows in sheets.items()}
        self.id = "fake-spreadsheet-id"
        self.client = None
        self.fetch_sheet_metadata_call_count = 0
        self._remaining_metadata_failures = metadata_fail_times
        self._metadata_fail_status = metadata_fail_status

    def fetch_sheet_metadata(self):
        self.fetch_sheet_metadata_call_count += 1
        if self._remaining_metadata_failures > 0:
            self._remaining_metadata_failures -= 1
            raise _make_api_error(self._metadata_fail_status)
        return {
            "sheets": [{"properties": {"title": name}} for name in self._worksheets]
        }


class _FakeResponse:
    """gspread.exceptions.APIError가 읽는 부분(status_code, json(), text)만
    흉내낸 응답 이중."""

    def __init__(self, status_code: int, *, body: str = ""):
        self.status_code = status_code
        self.text = body or f"error {status_code}"

    def json(self):
        # HTML 에러 페이지를 돌려주는 실제 502 응답을 재현한다 — 이 경우
        # APIError.code는 본문 파싱에 실패해 -1이 되고, 재시도 판정은
        # status_code로만 가능하다.
        raise ValueError("not JSON")


def _make_api_error(status_code: int) -> gspread.exceptions.APIError:
    return gspread.exceptions.APIError(_FakeResponse(status_code))


class _RecordingSleep:
    def __init__(self):
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _make_cache(spreadsheet: _FakeSpreadsheet, sleep=None) -> SheetCache:
    return SheetCache(
        spreadsheet,
        worksheet_factory=lambda properties: spreadsheet._worksheets[
            properties["title"]
        ],
        sleep=sleep or _RecordingSleep(),
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


def test_get_all_values_retries_transient_5xx_and_succeeds():
    """Google Sheets가 간헐적으로 내려주는 5xx는 재시도하면 대개 다음
    시도에서 성공한다 — 재시도가 없으면 그 커맨드 하나가 답글 없이 사라진다."""
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name"], ["아군1"]]})
    ws = spreadsheet._worksheets["캐릭터"]
    ws._remaining_failures = 2
    sleep = _RecordingSleep()
    cache = _make_cache(spreadsheet, sleep=sleep)

    assert cache.get_all_values("캐릭터") == [["name"], ["아군1"]]
    assert ws.get_values_call_count == 3
    assert sleep.delays == [1.0, 2.0]


def test_html_502_is_retried_even_though_api_error_code_is_minus_one():
    """502가 JSON이 아닌 HTML 에러 페이지로 오면 APIError.code가 -1이 된다.
    재시도 판정은 code가 아니라 HTTP 상태 코드를 봐야 한다."""
    error = _make_api_error(502)
    assert error.code == -1

    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name"], ["아군1"]]})
    ws = spreadsheet._worksheets["캐릭터"]
    ws._remaining_failures = 1
    ws._fail_status = 502
    cache = _make_cache(spreadsheet)

    assert cache.get_all_values("캐릭터") == [["name"], ["아군1"]]
    assert ws.get_values_call_count == 2


def test_retry_gives_up_after_max_attempts():
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name"], ["아군1"]]})
    ws = spreadsheet._worksheets["캐릭터"]
    ws._remaining_failures = 99
    cache = _make_cache(spreadsheet)

    try:
        cache.get_all_values("캐릭터")
        assert False, "예외가 발생해야 한다"
    except gspread.exceptions.APIError as error:
        assert error.response.status_code == 503

    assert ws.get_values_call_count == 3


def test_non_retryable_status_raises_immediately():
    """403(권한 없음)/429(할당량 초과)는 재시도해도 같은 결과이므로 즉시
    올려보낸다 — 괜히 백오프로 커맨드 처리만 지연시키지 않게."""
    for status_code in (403, 429):
        spreadsheet = _FakeSpreadsheet({"캐릭터": [["name"], ["아군1"]]})
        ws = spreadsheet._worksheets["캐릭터"]
        ws._remaining_failures = 99
        ws._fail_status = status_code
        cache = _make_cache(spreadsheet)

        try:
            cache.get_all_values("캐릭터")
            assert False, "예외가 발생해야 한다"
        except gspread.exceptions.APIError as error:
            assert error.response.status_code == status_code

        assert ws.get_values_call_count == 1


def test_metadata_fetch_is_retried_too():
    """멘션 처리 실패는 get_values()뿐 아니라 fetch_sheet_metadata()에서도
    발생했으므로(운영 로그의 503 사례) 이쪽도 재시도 대상이다."""
    spreadsheet = _FakeSpreadsheet(
        {"캐릭터": [["name"], ["아군1"]]}, metadata_fail_times=1
    )
    cache = _make_cache(spreadsheet)

    assert cache.worksheet("캐릭터") is spreadsheet._worksheets["캐릭터"]
    assert spreadsheet.fetch_sheet_metadata_call_count == 2


def test_retry_does_not_repeat_after_cached():
    """재시도 끝에 성공한 결과도 평소처럼 캐시돼야 한다 — 같은 멘션 안에서
    두 번째 조회가 다시 네트워크를 타면 안 된다."""
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name"], ["아군1"]]})
    ws = spreadsheet._worksheets["캐릭터"]
    ws._remaining_failures = 1
    cache = _make_cache(spreadsheet)

    cache.get_all_values("캐릭터")
    cache.get_all_values("캐릭터")

    assert ws.get_values_call_count == 2
