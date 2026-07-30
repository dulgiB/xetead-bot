"""필드/로그_전투/로그_비전투 시트 기록.

"필드" 시트는 전투 세션(본 전투/대련/상시전투)의 진행 상태 스냅샷이자
크래시 복구용 데이터를 겸한다 (과거 battle_persistence.py의 "전투 진행" 시트를
대체한다). "로그_전투"/"로그_비전투"는 커맨드 정산·비전투 행위 발생 시마다
행을 추가하는 append-only 로그다.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import gspread

from battle.core.commands.models import BattleLogEntry
from battle.objects.models import CharacterId
from utils.spreadsheet_bool import parse_spreadsheet_bool

from bot.load_data import update_character_curr_hp

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class BattleCommandLog:
    """커맨드 처리 결과를 로그_전투에 기록하기 위해 답글 발송 지점까지 들고 올라가는 자료.

    reply_ref(답글 status_id)는 아직 모르는 상태로 만들어지고,
    main.py에서 답글 전송 후 append_battle_log 호출 시 채워진다.
    """

    field_id: str
    round_n: int
    phase: str
    command_text: str
    is_main: bool = True
    entries: list[BattleLogEntry] = field(default_factory=list)
    error_trace: Optional[str] = None


@dataclass(frozen=True)
class NoncombatLogInfo:
    """로그_비전투 기록용 자료. reply_ref는 main.py에서 답글 전송 후 채워진다."""

    command_text: str
    dice_roll: str = ""
    result: str = ""
    error_trace: Optional[str] = None


_FIELD_SHEET = "필드"
_FIELD_HEADERS = [
    "id",
    "is_main",
    "started_at",
    "ended_at",
    "round",
    "phase",
    "characters_json",
]

_BATTLE_LOG_SHEET = "로그_전투"
_BATTLE_LOG_HEADERS = [
    "field_id",
    "round",
    "phase",
    "timestamp",
    "command_text",
    "dice_roll",
    "result",
    "error_trace",
    "reply_ref",
]

_NONCOMBAT_LOG_SHEET = "로그_비전투"
_NONCOMBAT_LOG_HEADERS = [
    "timestamp",
    "command_text",
    "dice_roll",
    "result",
    "error_trace",
    "reply_ref",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_or_create_worksheet(
    spreadsheet: gspread.Spreadsheet, name: str, headers: list[str]
) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(name, rows=100, cols=len(headers))
        ws.append_row(headers)
        return ws


# ---------------------------------------------------------------------------
# 필드
# ---------------------------------------------------------------------------


def build_field_characters(
    context: "BattlefieldContext", include_hp: bool
) -> list[dict]:
    """필드 캐릭터 스냅샷을 만든다.

    본 전투(include_hp=False)는 체력을 넣지 않는다 — 대신 "캐릭터" 시트의
    curr_hp가 진실 공급원이라 그쪽에서 복구한다. 대련/상시전투는 half-HP
    임시 캐릭터라 원본 캐릭터 시트에 쓸 수 없으므로 체력까지 필드에 담는다.
    """
    rows = []
    for char_id, char in context.characters.items():
        position = int(str(context.find_character_position(char_id)))
        row = {
            "name": char_id.name,
            "position": position,
            "remaining_cost": char.status.remaining_cost,
        }
        if include_hp:
            row["curr_hp"] = char.status.curr_hp
        rows.append(row)
    return rows


def write_back_changed_hp(
    spreadsheet: gspread.Spreadsheet,
    context: "BattlefieldContext",
    entries: list[BattleLogEntry],
) -> None:
    """entries 중 대미지/회복이 발생한 대상의 curr_hp를 "캐릭터" 시트에 반영한다.

    본 전투 전용 — 대련/상시전투는 half-HP 임시 캐릭터라 호출하면 안 된다.
    """
    changed_names = {
        entry.target_name
        for entry in entries
        if entry.result.startswith("대미지 ") or entry.result.startswith("회복 ")
    }
    for name in changed_names:
        char_id = CharacterId(name)
        char = context.characters.get(char_id)
        if char is None:
            continue
        update_character_curr_hp(spreadsheet, name, char.status.curr_hp)


def upsert_field_row(
    spreadsheet: gspread.Spreadsheet,
    field_id: str,
    is_main: bool,
    round_n: int,
    phase: str,
    characters: list[dict],
    ended: bool = False,
) -> None:
    """필드 시트에 전투 세션 스냅샷을 upsert한다.

    - field_id로 기존 행을 찾으면 그 행을 갱신한다.
    - 못 찾았고 is_main이면, 가장 위(가장 최근)의 is_main=TRUE 행을 대신 갱신한다
      (본 전투는 동시에 두 개 이상 진행되지 않는다는 전제).
    - 그래도 못 찾으면 새 행을 최상단(헤더 다음)에 삽입한다.
    - ended=True면 ended_at만 채우고 나머지는 기존 값을 유지한다.
    """
    ws = _get_or_create_worksheet(spreadsheet, _FIELD_SHEET, _FIELD_HEADERS)
    all_values = ws.get_all_values()
    data_rows = all_values[1:]

    row_idx = None
    for i, row in enumerate(data_rows, start=2):
        if row and row[0] == field_id:
            row_idx = i
            break

    if row_idx is None and is_main:
        for i, row in enumerate(data_rows, start=2):
            if row and len(row) > 1 and parse_spreadsheet_bool(row[1]):
                row_idx = i
                break

    characters_json = json.dumps(characters, ensure_ascii=False)

    if row_idx is not None:
        existing = all_values[row_idx - 1]
        existing = existing + [""] * (len(_FIELD_HEADERS) - len(existing))
        started_at = existing[2] or _now()
        ended_at = _now() if ended else existing[3]
        new_row = [
            field_id,
            is_main,
            started_at,
            ended_at,
            round_n,
            phase,
            characters_json,
        ]
        ws.update(
            f"A{row_idx}:G{row_idx}", [new_row], value_input_option="USER_ENTERED"
        )
        return

    new_row = [
        field_id,
        is_main,
        _now(),
        _now() if ended else "",
        round_n,
        phase,
        characters_json,
    ]
    ws.insert_rows([new_row], row=2, value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# 로그_전투
# ---------------------------------------------------------------------------


def append_battle_log(
    spreadsheet: gspread.Spreadsheet,
    field_id: str,
    round_n: int,
    phase: str,
    command_text: str,
    entries: list[BattleLogEntry],
    reply_ref: str = "",
    error_trace: Optional[str] = None,
) -> None:
    """커맨드 정산 결과를 로그_전투에 기록한다.

    entries가 비어 있으면(검증 실패 등) 에러 행 1개만 남긴다.
    entries가 있으면 대상별로 행을 하나씩 추가한다.
    """
    ws = _get_or_create_worksheet(
        spreadsheet, _BATTLE_LOG_SHEET, _BATTLE_LOG_HEADERS
    )
    timestamp = _now()

    if not entries:
        ws.append_row(
            [
                field_id,
                round_n,
                phase,
                timestamp,
                command_text,
                "",
                "",
                error_trace or "",
                reply_ref,
            ],
            value_input_option="USER_ENTERED",
        )
        return

    rows = [
        [
            field_id,
            round_n,
            phase,
            timestamp,
            command_text,
            entry.roll_display or "",
            entry.result,
            error_trace or "",
            reply_ref,
        ]
        for entry in entries
    ]
    ws.append_rows(rows, value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# 로그_비전투
# ---------------------------------------------------------------------------


def append_noncombat_log(
    spreadsheet: gspread.Spreadsheet,
    command_text: str,
    dice_roll: str = "",
    result: str = "",
    error_trace: Optional[str] = None,
    reply_ref: str = "",
) -> None:
    ws = _get_or_create_worksheet(
        spreadsheet, _NONCOMBAT_LOG_SHEET, _NONCOMBAT_LOG_HEADERS
    )
    ws.append_row(
        [
            _now(),
            command_text,
            dice_roll,
            result,
            error_trace or "",
            reply_ref,
        ],
        value_input_option="USER_ENTERED",
    )
