import logging
from typing import TYPE_CHECKING, Optional

import gspread

if TYPE_CHECKING:
    # bot.sheet_cache는 spreadsheets.inventory를 가져오므로(bot/load_data.py 경유),
    # 런타임 임포트는 순환 참조가 된다 — 타입 힌트 목적으로만 참조한다.
    from bot.sheet_cache import SheetCache

logger = logging.getLogger(__name__)

_INVENTORY_SHEET = "인벤토리"


class Inventory:
    """캐릭터별 아이템 보유 현황.

    `(캐릭터 이름, 아이템 이름)` → 보유 개수 dict를 감싸며,
    아이템 소비 시 메모리 개수를 차감하고 스프레드시트에도 즉시 write-back한다.
    (spreadsheet가 None이면 메모리 상에서만 동작 — 테스트/대련용.)

    배틀 코어가 gspread에 직접 의존하지 않도록 시트 I/O를 이 객체에 캡슐화한다.

    `cache`는 멘션 하나 처리 범위의 SheetCache로, 전투 세션 내내 유지되는 이
    객체와 수명이 다르다 — 생성자에서 한 번 받는 대신 `cache` 속성을
    호출측(handle_character_command 등, session/context를 다루는 지점)이
    매 멘션마다 최신 SheetCache로 갱신해야 한다. 갱신하지 않으면(None)
    캐시 없이 매번 직접 조회한다.
    """

    def __init__(
        self,
        counts: dict[tuple[str, str], int],
        spreadsheet: Optional[gspread.Spreadsheet] = None,
    ) -> None:
        self._counts = counts
        self._spreadsheet = spreadsheet
        self.cache: "Optional[SheetCache]" = None

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

    def _worksheet(self):
        return (
            self.cache.worksheet(_INVENTORY_SHEET)
            if self.cache is not None
            else self._spreadsheet.worksheet(_INVENTORY_SHEET)
        )

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
            ws = self._worksheet()
            values = (
                self.cache.get_all_values(_INVENTORY_SHEET)
                if self.cache is not None
                else ws.get_values(pad_values=True)
            )
            if not values:
                if create_if_missing:
                    ws.append_row(
                        [char_name, item_id, new_count],
                        value_input_option="USER_ENTERED",
                    )
                    if self.cache is not None:
                        self.cache.invalidate(_INVENTORY_SHEET)
                return
            header, rows = values[0], values[1:]
            name_col = header.index("character_name")
            item_col = header.index("item_id")
            count_col = header.index("count") + 1

            for idx, row in enumerate(rows, start=2):
                row_name = row[name_col] if name_col < len(row) else None
                row_item = row[item_col] if item_col < len(row) else None
                if row_name == char_name and row_item == item_id:
                    ws.update_cell(idx, count_col, new_count)
                    if self.cache is not None:
                        self.cache.invalidate(_INVENTORY_SHEET)
                    return

            if create_if_missing:
                ws.append_row(
                    [char_name, item_id, new_count], value_input_option="USER_ENTERED"
                )
                if self.cache is not None:
                    self.cache.invalidate(_INVENTORY_SHEET)
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
