import logging
from typing import Optional

import gspread

logger = logging.getLogger(__name__)

_INVENTORY_SHEET = "인벤토리"


class Inventory:
    """캐릭터별 아이템 보유 현황.

    `(캐릭터 이름, 아이템 이름)` → 보유 개수 dict를 감싸며,
    아이템 소비 시 메모리 개수를 차감하고 스프레드시트에도 즉시 write-back한다.
    (spreadsheet가 None이면 메모리 상에서만 동작 — 테스트/대련용.)

    배틀 코어가 gspread에 직접 의존하지 않도록 시트 I/O를 이 객체에 캡슐화한다.
    """

    def __init__(
        self,
        counts: dict[tuple[str, str], int],
        spreadsheet: Optional[gspread.Spreadsheet] = None,
    ) -> None:
        self._counts = counts
        self._spreadsheet = spreadsheet

    def get_count(self, char_name: str, item_id: str) -> int:
        return self._counts.get((char_name, item_id), 0)

    def consume(self, char_name: str, item_id: str, amount: int = 1) -> None:
        """아이템을 amount만큼 소비한다. 메모리 개수를 차감한 뒤 시트에 반영한다."""
        new_count = max(0, self.get_count(char_name, item_id) - amount)
        self._counts[(char_name, item_id)] = new_count
        self._write_back(char_name, item_id, new_count)

    def grant(self, char_name: str, item_id: str, amount: int = 1) -> None:
        """아이템을 amount만큼 지급한다 (양도 수령 등). 메모리 개수를 늘린 뒤
        시트에 반영한다. 기존에 보유 이력이 없는 캐릭터·아이템 조합이면
        인벤토리 시트에 새 행을 추가한다."""
        new_count = self.get_count(char_name, item_id) + amount
        self._counts[(char_name, item_id)] = new_count
        self._write_back(char_name, item_id, new_count, create_if_missing=True)

    def _write_back(
        self,
        char_name: str,
        item_id: str,
        new_count: int,
        create_if_missing: bool = False,
    ) -> None:
        if self._spreadsheet is None:
            return

        try:
            ws = self._spreadsheet.worksheet(_INVENTORY_SHEET)
            records = ws.get_all_records()
            header = ws.row_values(1)
            count_col = header.index("count") + 1

            for idx, row in enumerate(records, start=2):
                if row.get("character_name") == char_name and (
                    row.get("item_id") == item_id
                ):
                    ws.update_cell(idx, count_col, new_count)
                    return

            if create_if_missing:
                ws.append_row(
                    [char_name, item_id, new_count], value_input_option="USER_ENTERED"
                )
                return

            logger.warning(
                "'%s' 시트에서 (%s, %s) 행을 찾지 못해 개수를 기록하지 못했습니다.",
                _INVENTORY_SHEET,
                char_name,
                item_id,
            )
        except Exception:
            # 시트 기록 실패가 전투 진행을 막지 않도록 로깅 후 진행한다.
            logger.exception(
                "인벤토리 개수 기록 실패: (%s, %s) → %s",
                char_name,
                item_id,
                new_count,
            )
