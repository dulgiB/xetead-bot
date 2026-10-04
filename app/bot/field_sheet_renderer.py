"""공개용 "필드" 시트(관중 노출용 실시간 전투 UI) 렌더링.

`app/bot/log_sheets.py`의 "필드" 시트(자동화 DB, 기계 판독용 스냅샷)와는
별개다. 이 모듈이 갱신하는 시트는 별도 스프레드시트(`FIELD_SPREADSHEET_KEY`)에
있는, 사람이 보기 좋은 그리드 형태의 "필드" 시트다. 본 전투에만 사용한다
(대련/상시전투는 이 시트에 반영하지 않는다).

시트 레이아웃은 수기로 만든 템플릿을 따른다. 위쪽 셀은 `_BATTLE_NAME_CELL`/
`_ROUND_CELL`/`_PHASE_CELL`/`_FIELD_EFFECT_CELL`이고, 진영 격자의 행은 전부
`_HEADER_ROW`(아래 H, 1~7열 번호와 "아군 선언 내용" 헤더가 있는 고정 행)에서
파생된다:

- H-9 ~ H-1행: 적군 캐릭터 3슬롯 블록. H에 바로 인접한 3행이 슬롯0(메인)이고,
  슬롯이 늘어날수록 H에서 멀어지며 위로 쌓인다.
- H+1행부터 `CHARM_ROW_COUNT`행: 부적 행. 부적 하나가 행 하나를 차지하며,
  소지자 열 ± 부적 사거리를 병합해 이름을 적고 효과는 메모에 넣는다.
- 그 아래 9행: 아군 캐릭터 3슬롯 블록. 슬롯이 늘어날수록 아래로 쌓인다.
- 각 블록 옆 J:K 열은 병합된 셀 하나다 — 선언 내용을 "이름 [커맨드]" 줄
  단위로 `\n`을 이어붙여 그 한 셀에 통째로 쓰므로, 적 수가 많아도 그리드
  구조가 깨지지 않는다.
- 블록 바깥의 "적군"/"아군" 타이틀과 헤더 라벨은 고정 텍스트라 건드리지 않는다.

J:K 병합은 `ensure_merged=True`로 호출했을 때만 수행한다 — 전투 시작 시 한 번
병합해 두면 시트에 그대로 남는다. 부적 행의 병합은 소지자가 움직이면 바뀌므로
매번 다시 한다.

**한 번의 렌더링은 `spreadsheets.batchUpdate` 호출 한 번이다.** 병합·값·메모를
따로 보내면 쓰기가 3회로 늘고, 커맨드마다 렌더링하는 구조라 분당 할당량
(서비스 계정 60회)을 금방 깎는다. `updateCells`는 한 CellData에
`userEnteredValue`와 `note`를 함께 실을 수 있어 값과 메모를 같은 요청에 담을
수 있고, 병합 요청도 같은 배열 앞쪽에 둔다(요청은 배열 순서대로 적용된다).

값은 `stringValue`로 쓴다 — 격자 내용이 전부 텍스트라 숫자/수식 해석이 필요
없고, 해석을 켜 두면 "="로 시작하는 전투 이름 같은 입력이 수식이 된다.
`fields` 마스크는 `userEnteredValue,note`뿐이라 셀 서식은 건드리지 않는다.

"전투 이름" 칸은 `battle_name`이 주어졌을 때만 갱신한다. 병합된 셀은 좌상단
셀 하나에만 값을 써도 정상 반영된다.
"""

import re
from typing import TYPE_CHECKING, Optional

import gspread
from gspread.utils import a1_to_rowcol, rowcol_to_a1

from battle.core.commands.models import CharacterCommand
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    BattlefieldColumnIndex,
    BuffType,
    CombatStatType,
    FactionType,
)
from battle.objects.models import CharacterId
from battle.objects.passive_skill.passive_skill import PassiveSkillWrapperBuff
from bot.sheet_cache import SheetCache

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_character import CombatCharacter

# 버프 분류별 머리 기호. NEUTRAL은 이롭지도 해롭지도 않은 마커라 방향을 가진
# 삼각형 대신 중립적인 기호를 쓴다.
_BUFF_TYPE_ICON = {
    BuffType.BUFF: "▴",
    BuffType.DEBUFF: "▾",
    BuffType.NEUTRAL: "▪",
}

_FIELD_SHEET = "필드"

_COLUMN_COUNT = 7
_BATTLEFIELD_COLUMNS = [
    BattlefieldColumnIndex.COL1,
    BattlefieldColumnIndex.COL2,
    BattlefieldColumnIndex.COL3,
    BattlefieldColumnIndex.COL4,
    BattlefieldColumnIndex.COL5,
    BattlefieldColumnIndex.COL6,
    BattlefieldColumnIndex.COL7,
]

_BATTLE_NAME_CELL = "B3"
_ROUND_CELL = "B4"
_PHASE_CELL = "D6"
_FIELD_EFFECT_CELL = "D7"

# 전장에 걸린 필드 효과가 없을 때 그 칸에 적는 문구. 빈 칸으로 두면 "아직
# 렌더링되지 않은 것"과 구분되지 않는다.
_NO_FIELD_EFFECT_TEXT = "없음"

# 진영 블록 하나의 높이 (슬롯 3개 x 캐릭터당 3줄)
_FACTION_BLOCK_HEIGHT = CHARACTER_PER_COLUMN * 3  # 9

# 1~7 열 번호 / "아군 선언 내용" 헤더가 있는 행 (고정 텍스트). 아래 행
# 상수가 전부 여기서 파생되므로, 시트 위쪽에 행이 늘고 줄 때는 이 값만
# 맞추면 격자와 병합 범위가 함께 따라온다.
_HEADER_ROW = 19

_ENEMY_BLOCK_TOP = _HEADER_ROW - _FACTION_BLOCK_HEIGHT  # 10
_ENEMY_MAIN_ROW_START = _HEADER_ROW - 3  # 16 (슬롯0, 헤더에 바로 인접)
_ENEMY_BLOCK_BOTTOM = _HEADER_ROW - 1  # 18

# 템플릿에 만들어 둔 부적 행 수. 동시에 표시할 수 있는 부적 수의 상한이며,
# 템플릿의 행 수와 다르면 그 아래 아군 블록이 통째로 어긋난다.
CHARM_ROW_COUNT = 1
_CHARM_ROW_START = _HEADER_ROW + 1  # 20

_ALLY_MAIN_ROW_START = _CHARM_ROW_START + CHARM_ROW_COUNT  # 21 (슬롯0)
_ALLY_BLOCK_BOTTOM = _ALLY_MAIN_ROW_START + _FACTION_BLOCK_HEIGHT - 1  # 29

_DECLARE_NAME_COL = 10  # J (병합된 선언 내용 셀의 좌상단 — J10:K18 / J20:K29)

# 이미지로 캡처할 마지막 행(field_sheet_image). 아군 블록 아래로 "아군"
# 띠와 여백이 붙으므로 그만큼 더 잡는다.
EXPORT_BOTTOM_ROW = _ALLY_BLOCK_BOTTOM + 4  # 33


def render_public_field_sheet(
    spreadsheet: gspread.Spreadsheet,
    context: "BattlefieldContext",
    round_n: int,
    phase: str,
    enemy_declared: dict[CharacterId, list[CharacterCommand]],
    battle_name: Optional[str] = None,
    cache: Optional[SheetCache] = None,
    ensure_merged: bool = False,
) -> None:
    ws = (
        cache.worksheet(_FIELD_SHEET)
        if cache is not None
        else spreadsheet.worksheet(_FIELD_SHEET)
    )

    enemy_grid, enemy_declare_text, notes = _build_faction_block(
        context,
        FactionType.ENEMY,
        main_row_start=_ENEMY_MAIN_ROW_START,
        direction=-1,
        declared=enemy_declared,
    )
    ally_grid, ally_declare_text, ally_notes = _build_faction_block(
        context,
        FactionType.ALLY,
        main_row_start=_ALLY_MAIN_ROW_START,
        direction=1,
        declared={},
    )
    notes.update(ally_notes)

    charm_grid, charm_notes, charm_merges = _build_charm_rows(context)
    notes.update(charm_notes)

    field_effect_text, field_effect_note = _format_field_effect_cell(context)

    # 병합·값·메모를 한 요청에 모은다. 요청은 배열 순서대로 적용되므로
    # 병합을 먼저 둔다.
    requests: list[dict] = []
    if ensure_merged:
        requests.extend(
            _merge_request(
                ws.id, row, _DECLARE_NAME_COL, _DECLARE_NAME_COL + 1, last_row
            )
            for row, last_row in (
                (_ENEMY_BLOCK_TOP, _ENEMY_BLOCK_BOTTOM),
                (_CHARM_ROW_START, _ALLY_BLOCK_BOTTOM),
            )
        )
    requests.extend(_charm_merge_requests(ws.id, charm_merges))

    if battle_name is not None:
        requests.append(_value_request(ws.id, _BATTLE_NAME_CELL, battle_name))
    requests.append(_value_request(ws.id, _ROUND_CELL, f"ROUND {round_n}"))
    requests.append(_value_request(ws.id, _PHASE_CELL, phase))
    requests.append(
        _value_request(
            ws.id, _FIELD_EFFECT_CELL, field_effect_text, note=field_effect_note
        )
    )
    requests.append(
        _value_request(
            ws.id, rowcol_to_a1(_ENEMY_BLOCK_TOP, _DECLARE_NAME_COL), enemy_declare_text
        )
    )
    requests.append(
        _value_request(
            ws.id, rowcol_to_a1(_CHARM_ROW_START, _DECLARE_NAME_COL), ally_declare_text
        )
    )
    for first_row, grid in (
        (_ENEMY_BLOCK_TOP, enemy_grid),
        (_CHARM_ROW_START, charm_grid),
        (_ALLY_MAIN_ROW_START, ally_grid),
    ):
        requests.append(_grid_request(ws.id, first_row, grid, notes))

    spreadsheet.batch_update({"requests": requests})


# 그리드 값이 들어가는 첫 열 (B). 격자는 B~H 7열이다.
_GRID_FIRST_COL = 2


def _cell_data(value: str, note: str = "") -> dict:
    """updateCells에 넣을 CellData 하나.

    값이 빈 문자열이면 `userEnteredValue`를 아예 넣지 않는다 — fields 마스크가
    그 칸을 비워, 빈 문자열이 들어간 칸이 아니라 진짜 빈 칸이 된다.

    값은 항상 `stringValue`다. 이름·스탯 줄은 전부 텍스트이고, 수식/숫자
    해석(기존 USER_ENTERED)은 "="로 시작하는 전투 이름 같은 입력을 수식으로
    바꿔 버리는 쪽으로만 작용한다.
    """
    cell: dict = {}
    if value:
        cell["userEnteredValue"] = {"stringValue": value}
    cell["note"] = note
    return cell


def _grid_range(
    sheet_id: int, first_row: int, first_col: int, last_row: int, last_col: int
) -> dict:
    """1-indexed 행/열(양끝 포함)을 GridRange(0-indexed, 끝 열림)로 옮긴다."""
    return {
        "sheetId": sheet_id,
        "startRowIndex": first_row - 1,
        "endRowIndex": last_row,
        "startColumnIndex": first_col - 1,
        "endColumnIndex": last_col,
    }


def _merge_request(
    sheet_id: int,
    row: int,
    first_col: int,
    last_col: int,
    last_row: Optional[int] = None,
) -> dict:
    return {
        "mergeCells": {
            "range": _grid_range(
                sheet_id,
                row,
                first_col,
                last_row if last_row is not None else row,
                last_col,
            ),
            "mergeType": "MERGE_ALL",
        }
    }


def _value_request(
    sheet_id: int, cell_a1: str, value: str, note: Optional[str] = None
) -> dict:
    """단일 셀 하나를 쓰는 updateCells 요청.

    `note`를 주지 않으면 fields에서 note를 빼, 그 칸에 사람이 달아 둔 메모를
    건드리지 않는다.
    """
    row, col = a1_to_rowcol(cell_a1)
    cell = _cell_data(value, note or "")
    if note is None:
        cell.pop("note")
    return {
        "updateCells": {
            "range": _grid_range(sheet_id, row, col, row, col),
            "rows": [{"values": [cell]}],
            "fields": "userEnteredValue" if note is None else "userEnteredValue,note",
        }
    }


def _grid_request(
    sheet_id: int, first_row: int, grid: list[list[str]], notes: dict[str, str]
) -> dict:
    """격자 블록 하나(값 + 메모)를 쓰는 updateCells 요청.

    메모는 `notes`에 A1로 담겨 오므로 칸마다 찾아 붙이고, 없는 칸은 빈
    메모로 둔다 — 캐릭터가 빠진 자리에 이전 버프 메모가 남지 않게 하려면
    비우는 쪽이 맞다(기존 update_notes도 빈 문자열을 썼다).
    """
    rows = [
        {
            "values": [
                _cell_data(
                    value,
                    notes.get(
                        rowcol_to_a1(
                            first_row + row_offset, _GRID_FIRST_COL + col_offset
                        ),
                        "",
                    ),
                )
                for col_offset, value in enumerate(row_values)
            ]
        }
        for row_offset, row_values in enumerate(grid)
    ]
    return {
        "updateCells": {
            "range": _grid_range(
                sheet_id,
                first_row,
                _GRID_FIRST_COL,
                first_row + len(grid) - 1,
                _GRID_FIRST_COL + _COLUMN_COUNT - 1,
            ),
            "rows": rows,
            "fields": "userEnteredValue,note",
        }
    }


def _build_charm_rows(
    context: "BattlefieldContext",
) -> tuple[list[list[str]], dict[str, str], list[tuple[int, int, int]]]:
    """부적 행의 (값 격자, 메모, 병합할 (행, 시작 열, 끝 열)) 을 만든다.

    아군 소지자만 그린다 — 부적 행은 아군 블록에 붙어 있다. 상한을 넘는 부적은
    표시에서 빠진다([전투개시] 때 admin에게 알린다).
    """
    grid = [["" for _ in range(_COLUMN_COUNT)] for _ in range(CHARM_ROW_COUNT)]
    notes = {
        rowcol_to_a1(row, col + 2): ""
        for row in range(_CHARM_ROW_START, _ALLY_MAIN_ROW_START)
        for col in range(_COLUMN_COUNT)
    }
    merges: list[tuple[int, int, int]] = []

    auras = sorted(
        (
            aura
            for aura in context.charm_auras.as_list()
            if (holder := context.characters.get(aura.holder)) is not None
            and holder.faction == FactionType.ALLY
        ),
        key=lambda aura: (
            context.find_character_position(aura.holder).value,
            aura.holder.name,
            aura.item.id,
        ),
    )
    for offset, aura in enumerate(auras[:CHARM_ROW_COUNT]):
        row = _CHARM_ROW_START + offset
        center = context.find_character_position(aura.holder).value
        first = max(0, center - aura.item.attack_range)
        last = min(_COLUMN_COUNT - 1, center + aura.item.attack_range)
        grid[offset][first] = f"{aura.item.id}[{aura.holder.name}]"
        notes[rowcol_to_a1(row, first + 2)] = (
            f"[{aura.item.id}] {aura.passive.description}"
        )
        merges.append((row, first + 2, last + 2))

    return grid, notes, merges


def _charm_merge_requests(
    sheet_id: int, merges: list[tuple[int, int, int]]
) -> list[dict]:
    """부적 행의 병합을 이번 상태로 다시 잡는 요청. 이전 병합을 먼저 풀어야
    소지자가 움직였을 때 범위가 따라간다."""

    requests: list[dict] = [
        {
            "unmergeCells": {
                "range": _grid_range(
                    sheet_id,
                    _CHARM_ROW_START,
                    _GRID_FIRST_COL,
                    _ALLY_MAIN_ROW_START - 1,
                    _COLUMN_COUNT + 1,
                )
            }
        }
    ]
    for row, first_col, last_col in merges:
        if last_col > first_col:
            requests.append(_merge_request(sheet_id, row, first_col, last_col))
    return requests


def _assign_block_slots(
    context: "BattlefieldContext", faction: FactionType
) -> dict[BattlefieldColumnIndex, dict[int, CharacterId]]:
    """진영 블록에서 각 캐릭터가 설 행(슬롯 0~2)을 열별로 정한다.

    position_map의 슬롯 번호를 그대로 쓰지 않는 이유는 두 가지다. 캐릭터가
    빠지면 그 슬롯 키만 pop되므로(슬롯0이 빠지면 {1: b, 2: c}) 번호를 그대로
    행에 매핑하면 앞 칸이 빈칸으로 보이고, 반대로 열마다 따로 앞으로 당기면
    여러 열에 걸친 캐릭터가 열마다 다른 행에 그려져 덩치가 끊겨 보인다.
    그래서 왼쪽 열부터 훑으며 캐릭터마다 "자기가 걸친 열 전부에서 비어 있는
    가장 앞 행"을 한 번만 잡아, 다열 캐릭터가 모든 열에서 같은 행에 놓이게
    한다."""
    assigned: dict[BattlefieldColumnIndex, dict[int, CharacterId]] = {
        column: {} for column in _BATTLEFIELD_COLUMNS
    }
    placed: set[CharacterId] = set()

    for column in _BATTLEFIELD_COLUMNS:
        slots = context.position_map[faction][column]
        for char_id in (slots[i] for i in sorted(slots.keys())):
            if char_id in placed:
                continue
            columns = [
                col
                for col in context.find_character_columns(char_id)
                if col in assigned
            ]
            row = next(
                (
                    candidate
                    for candidate in range(CHARACTER_PER_COLUMN)
                    if all(candidate not in assigned[col] for col in columns)
                ),
                None,
            )
            if row is None:
                continue
            for col in columns:
                assigned[col][row] = char_id
            placed.add(char_id)

    return assigned


def _build_faction_block(
    context: "BattlefieldContext",
    faction: FactionType,
    *,
    main_row_start: int,
    direction: int,
    declared: dict[CharacterId, list[CharacterCommand]],
) -> tuple[list[list[str]], str, dict[str, str]]:
    """진영 블록 하나(9행 x 7열 캐릭터 그리드 + 선언 내용 병합 셀 텍스트)를 조립한다.

    `direction`은 슬롯이 늘어날수록 메인 행(슬롯0)에서 어느 쪽으로 멀어지는지를
    나타낸다 (적군은 -1: 위로, 아군은 +1: 아래로). 캐릭터 그리드는 블록의
    최상단 행부터 시작하는 상대 좌표라 `batch_update`에 그대로 넘길 수 있다.
    선언 내용은 J열 병합 셀 하나에 통째로 들어가므로 행 수 제약이 없다 —
    "이름 [커맨드]" 줄을 `\n`으로 이어붙인 문자열 하나로 반환한다.
    """
    block_top = min(
        main_row_start, main_row_start + direction * (CHARACTER_PER_COLUMN - 1) * 3
    )

    grid = [["" for _ in range(_COLUMN_COUNT)] for _ in range(_FACTION_BLOCK_HEIGHT)]
    notes: dict[str, str] = {}
    occupants_by_column = _assign_block_slots(context, faction)

    for col_idx, column in enumerate(_BATTLEFIELD_COLUMNS):
        occupants = occupants_by_column[column]
        sheet_col = col_idx + 2  # B=2

        for slot in range(CHARACTER_PER_COLUMN):
            name_row = main_row_start + direction * slot * 3
            stats_row = name_row + 1
            buff_row = name_row + 2
            buff_cell = rowcol_to_a1(buff_row, sheet_col)

            char_id = occupants.get(slot)
            if char_id is None:
                notes[buff_cell] = ""
                continue

            char = context.characters[char_id]
            grid[name_row - block_top][col_idx] = _format_name_line(char)
            grid[stats_row - block_top][col_idx] = _format_stats_line(char)

            buff_text, note_text = _format_buff_cell(context, char_id)
            grid[buff_row - block_top][col_idx] = buff_text
            notes[buff_cell] = note_text

    declare_lines = [
        f"{char_id.name} "
        + " ".join(_format_declared_command(command) for command in commands)
        for char_id, commands in declared.items()
    ]

    return grid, "\n".join(declare_lines), notes


def _format_declared_command(command: CharacterCommand) -> str:
    parts_text = []
    for part in command.parts:
        label = part.skill_id or part.type_.value
        targets_text = ", ".join(
            target.name if isinstance(target, CharacterId) else str(target)
            for target in part.targets
        )
        if targets_text:
            parts_text.append(f"[{label}/{targets_text}]")
        else:
            parts_text.append(f"[{label}]")
    return " ".join(parts_text)


def _format_name_line(char: "CombatCharacter") -> str:
    if char.hide_hp:
        hp_text = "?/?"
    else:
        hp_text = f"{char.status.curr_hp}/{char.status[CombatStatType.MAX_HP]}"
    remaining_cost = char.status.remaining_cost
    max_cost = char.status[CombatStatType.COST_PER_TURN]
    return f"{char.id.name}\n[{hp_text}] [{remaining_cost}/{max_cost}]"


def _format_stats_line(char: "CombatCharacter") -> str:
    atk = char.status[CombatStatType.ATK]
    attack_range = char.status[CombatStatType.RANGE]
    attack_kind = "마법" if char.status.is_magic_attacker else "물리"
    return (
        f"ATK {atk} · RAN {attack_range}\n{attack_kind} · 마력적응 {_m_res_icon(char)}"
    )


def _m_res_icon(char: "CombatCharacter") -> str:
    """마력적응 아이콘. 저항(유리)은 ▴, 취약(불리)은 ▾, 보통은 ⚬."""
    resistance_value = char.status.m_res.value
    if resistance_value > 0:
        return "▾"
    elif resistance_value < 0:
        return "▴"
    return "⚬"


# description은 자신이 부여하는 다른 버프를 "▸ [버프id]: 설명" 줄로 미리
# 문서화해 둘 수 있다. 부여 전에는 유용한 미리보기지만, 부여되고 나면 그
# 버프가 자기 note 줄을 따로 갖게 되어 같은 설명이 두 번 보인다.
_REFERENCED_BUFF_LINE = re.compile(r"^▸\s*\[([^\]]+)]")


def _strip_lines_for_already_present_buffs(
    description: str, active_buff_ids: set[str]
) -> str:
    """description에서 "▸ [버프id]: ..." 형태의 줄 중, 그 버프id가 이미
    같은 캐릭터에게 부여되어 있는 것은 제거한다 — 그 버프가 자기 자신의
    note 줄로 이미 표시되므로 중복이다."""
    kept_lines = [
        line
        for line in description.splitlines()
        if not (
            (match := _REFERENCED_BUFF_LINE.match(line.strip()))
            and match.group(1) in active_buff_ids
        )
    ]
    return "\n".join(kept_lines)


def _format_field_effect_cell(context: "BattlefieldContext") -> tuple[str, str]:
    """ "필드 효과" 칸에 넣을 (표시 텍스트, 메모 텍스트).

    필드 효과는 캐릭터가 아니라 전장에 붙어 있어 캐릭터별 버프 칸에는 잡히지
    않으므로(센티넬 홀더에 등록된다) 따로 보여주지 않으면 어디에도 드러나지
    않는다. 설명은 버프 칸과 같은 방식으로 셀 메모에 담는다 — 그리드가
    좁아 본문에 설명까지 넣으면 이름이 밀린다.
    """
    effects = context.field_effects.as_list()
    if not effects:
        return _NO_FIELD_EFFECT_TEXT, ""

    # 한 행짜리 칸이라 줄을 나누면 두 번째부터 잘린다 — 가운뎃점으로 이어
    # 붙여 한 줄에 담는다.
    display_text = " · ".join(effect.display_label() for effect in effects)
    note_lines = [f"[{effect.id}] {effect.description}" for effect in effects]
    return display_text, "\n".join(note_lines)


def _format_buff_cell(
    context: "BattlefieldContext", char_id: CharacterId
) -> tuple[str, str]:
    buffs = context.buff_container.get_buffs_by(char_id, None)
    if not buffs:
        return "", ""

    active_buff_ids = {buff.id for buff in buffs}
    display_lines = []
    note_lines = []
    seen_passive_labels: set[str] = set()
    for buff in buffs:
        label = buff.display_id_label()
        # 패시브 하나가 역할별로 여러 버프 인스턴스로 나뉘어 등록될 수 있다
        # (passive_skill.py 참고) — 시트에는 패시브 하나로만 보여야 하므로
        # 같은 라벨의 두 번째 이후는 건너뛴다.
        if isinstance(buff, PassiveSkillWrapperBuff):
            if label in seen_passive_labels:
                continue
            seen_passive_labels.add(label)
        icon = _BUFF_TYPE_ICON[buff.buff_type]
        stack_count = buff.stack_count if buff.max_stack is not None else None
        display_lines.append(f"{icon} {label}{buff.duration.display_text(stack_count)}")
        description = _strip_lines_for_already_present_buffs(
            buff.get_description(context), active_buff_ids
        )
        note_lines.append(f"[{label}] {description}")

    return "\n".join(display_lines), "\n".join(note_lines)
