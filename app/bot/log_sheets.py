"""필드/로그_전투/로그_비전투 시트 기록.

"필드" 시트는 전투 세션(본 전투/대련/상시전투)의 진행 상태 스냅샷이자
크래시 복구용 데이터를 겸한다 (과거 battle_persistence.py의 "전투 진행" 시트를
대체한다). "로그_전투"/"로그_비전투"는 커맨드 정산·비전투 행위 발생 시마다
행을 추가하는 append-only 로그다.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import gspread

from battle.core.commands.models import BattleLogEntry
from battle.objects.models import CharacterId
from utils.spreadsheet_bool import parse_spreadsheet_bool

from bot.sheet_cache import SheetCache

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext

logger = logging.getLogger(__name__)


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
    spreadsheet: gspread.Spreadsheet,
    name: str,
    headers: list[str],
    cache: Optional[SheetCache] = None,
) -> gspread.Worksheet:
    try:
        return cache.worksheet(name) if cache is not None else spreadsheet.worksheet(
            name
        )
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


_UNFORMATTED = gspread.utils.ValueRenderOption.unformatted


def _load_hp_write_targets(
    spreadsheet: gspread.Spreadsheet, cache: Optional[SheetCache] = None
) -> dict[str, tuple[gspread.Worksheet, int, int]]:
    """이름 → (worksheet, 행 번호, curr_hp 열 번호) 매핑을 시트당 1회 읽기로
    구축한다. `cache`가 주어지면 load_char_data()가 이미 읽어 둔 값을 그대로
    재사용해(같은 (시트, value_render_option) 조합이면 캐시 히트) 추가
    네트워크 호출 없이 매핑만 만든다."""
    targets: dict[str, tuple[gspread.Worksheet, int, int]] = {}
    for sheet_name in ("캐릭터", "에너미"):
        try:
            ws = cache.worksheet(sheet_name) if cache is not None else spreadsheet.worksheet(
                sheet_name
            )
        except gspread.exceptions.WorksheetNotFound:
            continue
        if cache is not None:
            values = cache.get_all_values(sheet_name, value_render_option=_UNFORMATTED)
        else:
            values = ws.get_values(value_render_option=_UNFORMATTED, pad_values=True)
        if not values:
            continue
        header = values[0]
        if "curr_hp" not in header or "name" not in header:
            continue
        hp_col = header.index("curr_hp") + 1
        name_col = header.index("name")
        for idx, row in enumerate(values[1:], start=2):
            name = row[name_col] if name_col < len(row) else ""
            if name and name not in targets:
                targets[name] = (ws, idx, hp_col)
    return targets


def write_back_changed_hp(
    spreadsheet: gspread.Spreadsheet,
    context: "BattlefieldContext",
    entries: list[BattleLogEntry],
    cache: Optional[SheetCache] = None,
) -> None:
    """entries 중 대미지/회복이 발생한 대상의 curr_hp를 "캐릭터" 시트에 반영한다.

    본 전투 전용 — 대련/상시전투는 half-HP 임시 캐릭터라 호출하면 안 된다.

    호출측(캐릭터 커맨드 처리, 페이즈 전환 등)은 이미 커맨드/버프 처리를
    마친 뒤 이 함수를 호출한다 — 여기서 예외가 위로 전파되면 이미 끝난
    처리의 응답 자체가 사라지고, 사용자가 재시도하면 같은 행동이 중복
    적용되는 문제로 이어진다. 그래서 캐릭터별로 실패를 흡수하고 로깅만
    하며(한 캐릭터가 실패해도 나머지는 계속 반영), 절대 위로 전파하지
    않는다. 실패해도 라이브 세션 상태(context)는 이미 정확하므로, 다음
    성공적인 write-back 시점에 시트도 자연히 다시 맞춰진다.

    이름→행 매핑을 시트당 1회만 읽어서 구축한 뒤(_load_hp_write_targets)
    변경된 캐릭터 수만큼 그 매핑을 재사용한다 — 바뀐 캐릭터가 N명이어도
    읽기는 시트당 1회로 고정된다(쓰기는 여전히 캐릭터별 update_cell).
    """
    changed_names = {
        entry.target_name
        for entry in entries
        if entry.result.startswith("대미지 ") or entry.result.startswith("회복 ")
    }
    if not changed_names:
        return

    try:
        targets = _load_hp_write_targets(spreadsheet, cache)
    except Exception:
        logger.exception("체력 시트 반영 대상 조회 실패")
        return

    for name in changed_names:
        char_id = CharacterId(name)
        char = context.characters.get(char_id)
        # 라운드 종료 시점에 체력 0으로 필드에서 이미 제거된 대상이면(예:
        # 라운드 종료 DoT로 인한 탈락) context.characters에 더 이상 없다 —
        # 이 시점에 존재하지 않는다는 것 자체가 탈락을 의미하므로 0으로 기록한다.
        curr_hp = char.status.curr_hp if char is not None else 0
        target = targets.get(name)
        if target is None:
            logger.error(
                "'%s'을 캐릭터/에너미 시트에서 찾을 수 없어 체력(%s) 반영 실패",
                name,
                curr_hp,
            )
            continue
        ws, row, hp_col = target
        try:
            ws.update_cell(row, hp_col, curr_hp)
        except Exception:
            logger.exception("'%s'의 체력(%s) 시트 반영 실패", name, curr_hp)


def upsert_field_row(
    spreadsheet: gspread.Spreadsheet,
    field_id: str,
    is_main: bool,
    round_n: int,
    phase: str,
    characters: list[dict],
    ended: bool = False,
    cache: Optional[SheetCache] = None,
) -> None:
    """필드 시트에 전투 세션 스냅샷을 upsert한다.

    - field_id로 기존 행을 찾으면 그 행을 갱신한다.
    - 못 찾았고 is_main이면, 가장 위(가장 최근)의 is_main=TRUE 행을 대신 갱신한다
      (본 전투는 동시에 두 개 이상 진행되지 않는다는 전제).
    - 그래도 못 찾으면 새 행을 최상단(헤더 다음)에 삽입한다.
    - ended=True면 ended_at만 채우고 나머지는 기존 값을 유지한다.

    `cache`가 주어지면 초기 조회에 재사용하되, 이 함수 자체가 "필드" 시트에
    쓰기를 수행하므로 반환 직전 반드시 그 시트의 캐시 엔트리를 무효화한다 —
    같은 커맨드 처리 중 upsert_field_row가 다시 호출됐을 때 방금 쓴 내용을
    못 보고 중복 삽입하는 것을 막기 위함이다.
    """
    ws = _get_or_create_worksheet(spreadsheet, _FIELD_SHEET, _FIELD_HEADERS, cache=cache)
    if cache is not None:
        all_values = cache.get_all_values(_FIELD_SHEET)
    else:
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
        if cache is not None:
            cache.invalidate(_FIELD_SHEET)
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
    if cache is not None:
        cache.invalidate(_FIELD_SHEET)


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
    cache: Optional[SheetCache] = None,
) -> None:
    """커맨드 정산 결과를 로그_전투에 기록한다.

    entries가 비어 있으면(검증 실패 등) 에러 행 1개만 남긴다.
    entries가 있으면 대상별로 행을 하나씩 추가한다.
    """
    ws = _get_or_create_worksheet(
        spreadsheet, _BATTLE_LOG_SHEET, _BATTLE_LOG_HEADERS, cache=cache
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
    cache: Optional[SheetCache] = None,
) -> None:
    ws = _get_or_create_worksheet(
        spreadsheet, _NONCOMBAT_LOG_SHEET, _NONCOMBAT_LOG_HEADERS, cache=cache
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
