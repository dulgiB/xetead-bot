import json
from typing import TYPE_CHECKING

import gspread

if TYPE_CHECKING:
    from bots.mastodon_bot.main import BotState

_SHEET_NAME = "전투 진행"
_HEADERS = ["battle_key", "milestone_n", "round", "phase", "finished", "characters_json"]


def _get_or_create_worksheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(_SHEET_NAME, rows=100, cols=len(_HEADERS))
        ws.append_row(_HEADERS)
        return ws


def _build_characters_json(state: "BotState") -> str:
    ctx = state.session.context
    rows = []
    for char_id, char in ctx.characters.items():
        from battle.objects.define import FactionType
        faction = char.faction.value
        position = int(str(ctx.find_character_position(char_id)))
        rows.append({
            "name": char_id.name,
            "faction": faction,
            "position": position,
            "curr_hp": char.status.curr_hp,
            "remaining_cost": char.status.remaining_cost,
        })
    return json.dumps(rows, ensure_ascii=False)


def save_battle_state(spreadsheet: gspread.Spreadsheet, state: "BotState") -> None:
    """현재 전투 상태를 스프레드시트에 upsert한다."""
    ws = _get_or_create_worksheet(spreadsheet)
    session = state.session
    battle_key = state.battle_key

    new_row = [
        battle_key,
        session.context.milestone_n,
        session.round_n,
        session.current_phase.value,
        False,
        _build_characters_json(state),
    ]

    all_values = ws.get_all_values()
    for row_idx, row in enumerate(all_values[1:], start=2):
        if row and row[0] == battle_key:
            ws.update(f"A{row_idx}:F{row_idx}", [new_row])
            return

    ws.append_row(new_row)


def mark_battle_finished(spreadsheet: gspread.Spreadsheet, battle_key: str) -> None:
    """finished 컬럼을 True로 업데이트한다."""
    ws = _get_or_create_worksheet(spreadsheet)
    all_values = ws.get_all_values()
    for row_idx, row in enumerate(all_values[1:], start=2):
        if row and row[0] == battle_key:
            finished_col = _HEADERS.index("finished") + 1
            ws.update_cell(row_idx, finished_col, True)
            return
