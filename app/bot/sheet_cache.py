"""스프레드시트 원본 값과 시트 메타데이터를 재사용하기 위한 캐시.

봇이 멘션 하나를 처리할 때마다(reload_char_data → 실제 커맨드 처리 →
write-back → 필드 시트 기록) "캐릭터"/"에너미" 시트를 여러 지점에서
각자 다시 읽으면 Google Sheets 읽기 할당량(분당 60회/서비스 계정)을 금방
소진한다. 같은 (시트 이름, value_render_option) 조합을 두 번째 요청할
때부터는 네트워크 호출 없이 이전 결과를 그대로 돌려준다.

캐시는 수명이 다른 두 층으로 나뉜다.

- **시트 값**: 멘션 하나의 처리 범위에서만 유효하다. 멘션마다
  `reset_values()`로 비우므로, 전투 중 스프레드시트를 실시간으로 고쳐도
  (참전 신청, GM의 행 수정 등) 다음 멘션부터는 다시 최신 값을 읽는다.
- **시트 메타데이터**(시트 목록·id): 여러 멘션에 걸쳐 재사용하되, 읽은 지
  `_METADATA_TTL_SEC`가 지나면 다음 멘션에서 다시 읽는다.
  gspread.Spreadsheet.worksheet(name)은 이름이 무엇이든 매번 스프레드시트
  전체 메타데이터를 새로 읽어오는데, 커맨드가 몰리는 전투 중에 멘션마다
  다시 읽을 이유는 없다. 그렇다고 계속 들고 있으면 GM이 시트를 지우고 같은
  이름으로 다시 만들었을 때(템플릿 재복사 등) 바뀐 시트 id를 끝내 모르고,
  id로 요청하는 렌더링·이미지 캡처가 재기동 전까지 실패한다.
  없는 이름을 찾았는데 메타데이터가 이전 멘션에서 읽은 것이면 한 번 다시
  읽어 확인한다 — 그 사이 새로 생긴 시트(봇이 만든 로그 시트 등)를 놓치지
  않기 위해서다. 행 수처럼 쓰기로 달라지는 속성을 읽는 쪽은 그 쓰기 뒤에
  `invalidate_metadata()`를 부른다.

쓰기(update_cell, batch_update 등)는 캐싱하지 않는다 — 이 캐시는 순수하게
읽기 중복만 제거한다. 같은 멘션 처리 중 어떤 시트에 쓰기를 수행했다면
`invalidate()`로 그 시트의 캐시를 지워야 한다(그러지 않으면 같은 멘션의
뒤쪽 코드가 쓰기 전 값을 다시 읽을 수 있다).

읽기 호출은 5xx 응답에 한해 지수 백오프로 재시도한다 — Google Sheets가
간헐적으로 502/503을 내려주는데, 재시도가 없으면 그 커맨드 하나가
`_process_notification()`의 예외 처리로 흡수되어 답글 없이 사라진다.
"""

import logging
import time
from typing import Any, Callable, Mapping, Optional, Sequence, TypeVar

import gspread
from gspread.utils import (
    ValueRenderOption,
    absolute_range_name,
    fill_gaps,
    numericise_all,
    to_records,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# 재시도하면 대개 다음 시도에 성공하는 일시 장애. 4xx와 429는 재시도해도
# 같은 결과이므로 제외한다.
_RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
_MAX_ATTEMPT_COUNT = 3
_METADATA_TTL_SEC = 300.0
_RETRY_BASE_DELAY_SEC = 1.0


def _is_retryable(error: gspread.exceptions.APIError) -> bool:
    """`APIError.code`는 응답 본문 JSON의 `error.code`에서 읽은 값이라,
    Google이 5xx를 JSON이 아닌 HTML 에러 페이지로 돌려주면 파싱에 실패해
    -1이 된다(실제 502가 이 형태로 온다). HTTP 상태 코드는 그런 경우에도
    정확하므로 이쪽을 판정 기준으로 쓴다."""
    return error.response.status_code in _RETRYABLE_STATUS_CODES


def _padded(values: list[list]) -> list[list]:
    """`Worksheet.get_values(pad_values=True)`와 같은 모양으로 맞춘다."""
    try:
        return fill_gaps(values)
    except KeyError:
        return [[]]


class SheetCache:
    def __init__(
        self,
        spreadsheet: gspread.Spreadsheet,
        *,
        worksheet_factory: Optional[
            Callable[[dict[str, Any]], gspread.Worksheet]
        ] = None,
        sleep: Optional[Callable[[float], None]] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._spreadsheet = spreadsheet
        self._sheet_metadata: Optional[Mapping[str, Any]] = None
        self._metadata_fetched_since_reset = False
        self._metadata_fetched_at = 0.0
        self._worksheets: dict[str, gspread.Worksheet] = {}
        self._raw_values: dict[tuple[str, Optional[ValueRenderOption]], list[list]] = {}
        # HTTP 클라이언트 없이 캐싱 로직만 검증하기 위한 테스트 seam.
        self._worksheet_factory = worksheet_factory or self._build_worksheet
        # 재시도 백오프를 테스트에서 실제로 기다리지 않게 하기 위한 seam.
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic

    def _call_with_retry(self, description: str, call: Callable[[], _T]) -> _T:
        """`call`이 재시도 가능한 5xx로 실패하면 지수 백오프 후 다시 부른다.
        마지막 시도의 실패와 재시도 대상이 아닌 예외는 그대로 올려보낸다.

        최악의 경우 호출 하나가 백오프로 `_RETRY_BASE_DELAY_SEC`의 합만큼
        (기본값 기준 3초) 블로킹된다 — 멘션은 워커 스레드 하나가 순차
        처리하므로, Sheets가 완전히 죽은 동안에는 뒤따르는 커맨드 처리도
        그만큼 밀린다. 어차피 그 상황에서는 재시도 여부와 무관하게 전부
        실패하므로, 간헐적 장애를 흡수하는 이득이 더 크다고 보고 감수한다."""
        for attempt in range(1, _MAX_ATTEMPT_COUNT):
            try:
                return call()
            except gspread.exceptions.APIError as error:
                if not _is_retryable(error):
                    raise
                delay = _RETRY_BASE_DELAY_SEC * 2 ** (attempt - 1)
                logger.warning(
                    "스프레드시트 %s 실패 (%d/%d회), %.1f초 후 재시도: %s",
                    description,
                    attempt,
                    _MAX_ATTEMPT_COUNT,
                    delay,
                    error,
                )
                self._sleep(delay)
        return call()

    def _build_worksheet(self, properties: dict[str, Any]) -> gspread.Worksheet:
        return gspread.Worksheet(
            self._spreadsheet,
            properties,
            self._spreadsheet.id,
            self._spreadsheet.client,
        )

    def _fetch_metadata(self) -> Mapping[str, Any]:
        self._sheet_metadata = self._call_with_retry(
            "메타데이터 조회", self._spreadsheet.fetch_sheet_metadata
        )
        self._metadata_fetched_since_reset = True
        self._metadata_fetched_at = self._clock()
        return self._sheet_metadata

    @staticmethod
    def _find_properties(
        metadata: Mapping[str, Any], name: str
    ) -> Optional[dict[str, Any]]:
        for sheet in metadata["sheets"]:
            if sheet["properties"]["title"] == name:
                return sheet["properties"]
        return None

    def worksheet(self, name: str) -> gspread.Worksheet:
        if name not in self._worksheets:
            metadata = self._sheet_metadata
            if metadata is None:
                metadata = self._fetch_metadata()
            properties = self._find_properties(metadata, name)
            if properties is None and not self._metadata_fetched_since_reset:
                properties = self._find_properties(self._fetch_metadata(), name)
            if properties is None:
                raise gspread.exceptions.WorksheetNotFound(name)
            self._worksheets[name] = self._worksheet_factory(properties)
        return self._worksheets[name]

    def get_all_values(
        self,
        name: str,
        value_render_option: Optional[ValueRenderOption] = None,
    ) -> list[list]:
        key = (name, value_render_option)
        if key not in self._raw_values:
            worksheet = self.worksheet(name)
            self._raw_values[key] = self._call_with_retry(
                f'"{name}" 시트 읽기',
                lambda: worksheet.get_values(
                    value_render_option=value_render_option, pad_values=True
                ),
            )
        return self._raw_values[key]

    def prefetch_values(
        self,
        names: Sequence[str],
        value_render_option: Optional[ValueRenderOption] = None,
    ) -> None:
        """여러 시트의 값을 요청 한 번(`values:batchGet`)으로 읽어 캐시에 채운다.
        결과는 시트마다 `get_all_values()`를 부른 것과 같다. 없는 시트는
        건너뛰므로, 찾는 쪽이 `get_all_values()`에서 평소처럼
        `WorksheetNotFound`를 받는다."""
        pending: list[str] = []
        for name in names:
            if (name, value_render_option) in self._raw_values:
                continue
            try:
                self.worksheet(name)
            except gspread.exceptions.WorksheetNotFound:
                continue
            pending.append(name)
        if not pending:
            return
        params: dict[str, Any] = {}
        if value_render_option is not None:
            params["valueRenderOption"] = value_render_option
        response = self._call_with_retry(
            f"{', '.join(pending)} 시트 일괄 읽기",
            lambda: self._spreadsheet.values_batch_get(
                [absolute_range_name(name) for name in pending], params=params
            ),
        )
        for name, value_range in zip(pending, response["valueRanges"]):
            self._raw_values[(name, value_render_option)] = _padded(
                value_range.get("values", [[]])
            )

    def get_all_records(
        self,
        name: str,
        value_render_option: Optional[ValueRenderOption] = None,
    ) -> list[dict]:
        """gspread.Worksheet.get_all_records()와 동일한 결과(헤더 행을 키로,
        나머지 행을 numericise한 값)를 캐시된 원본 값 위에서 재구성한다."""
        raw = self.get_all_values(name, value_render_option)
        if not raw or raw == [[]]:
            return []
        headers, *rows = raw
        rows = [numericise_all(row) for row in rows]
        return to_records(headers, rows)

    def invalidate(self, name: str) -> None:
        self._raw_values = {
            key: value for key, value in self._raw_values.items() if key[0] != name
        }

    def reset_values(self) -> None:
        self._raw_values = {}
        self._metadata_fetched_since_reset = False
        if self._clock() - self._metadata_fetched_at >= _METADATA_TTL_SEC:
            self.invalidate_metadata()

    def invalidate_metadata(self) -> None:
        self._sheet_metadata = None
        self._worksheets = {}
