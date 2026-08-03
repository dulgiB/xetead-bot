"""커맨드 하나를 처리하는 동안 스프레드시트 원본 값을 재사용하기 위한 캐시.

봇이 멘션 하나를 처리할 때마다(reload_char_data → 실제 커맨드 처리 →
write-back → 필드 시트 기록) "캐릭터"/"에너미" 시트를 여러 지점에서
각자 다시 읽어 Google Sheets 읽기 할당량(분당 60회/서비스 계정)을 금방
소진했다. 이 클래스는 멘션 하나의 처리 범위 안에서만 유효한 캐시로,
같은 (시트 이름, value_render_option) 조합을 두 번째 요청할 때부터는
네트워크 호출 없이 이전 결과를 그대로 돌려준다.

gspread.Spreadsheet.worksheet(name)은 이름이 무엇이든 매번 스프레드시트
전체 메타데이터(fetch_sheet_metadata, 시트 목록 전체)를 새로 읽어온다 —
"캐릭터"와 "에너미"처럼 서로 다른 이름을 조회할 때도 내용이 완전히 같은
메타데이터를 두 번 읽는 낭비가 있었다. 이 캐시는 그 메타데이터 자체를
인스턴스당 한 번만 가져와 모든 이름의 worksheet() 조회에 재사용한다.

캐시는 `on_notification()` 시작 시 매번 새로 만들어(`BotState.sheet_cache`)
그 멘션 처리가 끝나면 다음 멘션에서 새 인스턴스로 교체된다 — 커맨드 사이에는
공유하지 않는다. 전투 중 스프레드시트를 실시간으로 고쳐도(참전 신청, GM의
행 수정 등) 다음 멘션부터는 다시 최신 값을 읽는다는 기존 설계를 그대로
유지하기 위함이다.

쓰기(update_cell, batch_update 등)는 캐싱하지 않는다 — 이 캐시는 순수하게
읽기 중복만 제거한다. 같은 멘션 처리 중 어떤 시트에 쓰기를 수행했다면
`invalidate()`로 그 시트의 캐시를 지워야 한다(그러지 않으면 같은 멘션의
뒤쪽 코드가 쓰기 전 값을 다시 읽을 수 있다).
"""

from typing import Optional

import gspread
from gspread.utils import ValueRenderOption, numericise_all, to_records


class SheetCache:
    def __init__(
        self,
        spreadsheet: gspread.Spreadsheet,
        *,
        worksheet_factory=None,
    ):
        self._spreadsheet = spreadsheet
        self._sheet_metadata: Optional[dict] = None
        self._worksheets: dict[str, gspread.Worksheet] = {}
        self._raw_values: dict[
            tuple[str, Optional[ValueRenderOption]], list[list]
        ] = {}
        # 테스트에서 실제 gspread.Worksheet(HTTP 클라이언트 필요) 없이도
        # worksheet() 캐싱/메타데이터 재사용 로직을 검증할 수 있도록 하는 seam.
        self._worksheet_factory = worksheet_factory or self._build_worksheet

    def _build_worksheet(self, properties: dict) -> gspread.Worksheet:
        return gspread.Worksheet(
            self._spreadsheet,
            properties,
            self._spreadsheet.id,
            self._spreadsheet.client,
        )

    def worksheet(self, name: str) -> gspread.Worksheet:
        """gspread.Spreadsheet.worksheet()는 이름과 무관하게 매번
        fetch_sheet_metadata()(스프레드시트 전체 시트 목록)를 새로 호출한다 —
        "캐릭터"/"에너미"/"필드" 등 이름이 다른 시트를 각각 조회하면 매번
        똑같은 전체 메타데이터를 중복해서 읽어오는 셈이다. 여기서는 그
        메타데이터 자체를 인스턴스당 한 번만 가져와 모든 이름 조회에
        재사용한다."""
        if name not in self._worksheets:
            if self._sheet_metadata is None:
                self._sheet_metadata = self._spreadsheet.fetch_sheet_metadata()
            try:
                item = next(
                    sheet
                    for sheet in self._sheet_metadata["sheets"]
                    if sheet["properties"]["title"] == name
                )
            except StopIteration:
                raise gspread.exceptions.WorksheetNotFound(name)
            self._worksheets[name] = self._worksheet_factory(item["properties"])
        return self._worksheets[name]

    def get_all_values(
        self,
        name: str,
        value_render_option: Optional[ValueRenderOption] = None,
    ) -> list[list]:
        key = (name, value_render_option)
        if key not in self._raw_values:
            self._raw_values[key] = self.worksheet(name).get_values(
                value_render_option=value_render_option, pad_values=True
            )
        return self._raw_values[key]

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
