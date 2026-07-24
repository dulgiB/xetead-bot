"""공개용 "필드" 시트(관중 노출용 실시간 전투 UI) 렌더링.

`app/bot/log_sheets.py`의 "필드" 시트(자동화 DB, 기계 판독용 스냅샷)와는
별개다. 이 모듈이 갱신하는 시트는 별도 스프레드시트(`FIELD_SPREADSHEET_KEY`)에
있는, 사람이 보기 좋은 그리드 형태의 "필드" 시트다. 본 전투에만 사용한다
(대련/상시전투는 이 시트에 반영하지 않는다).

시트 레이아웃은 수기로 만들어진 기존 템플릿을 그대로 따른다 (행 번호는
템플릿 기준 고정값):

- B4 (병합 B4:H4): "ROUND {n}"
- D6 (병합 D6:G6): 현재 페이즈 값 (라벨 "현재 페이즈"는 C6에 고정 텍스트로 이미 있음)
- 8행: "적군" 타이틀(B8:H8) / "적군 선언 내용" 헤더(J8:K8) — 고정 텍스트, 건드리지 않음
- 9~17행: 적군 캐릭터 3슬롯 블록. 헤더(18행)에 바로 인접한 15~17행이 슬롯0(메인),
  그 위 12~14행이 슬롯1, 9~11행이 슬롯2 — 슬롯이 늘어날수록 헤더에서 멀어지며 위로 쌓인다.
  같은 9~17행의 J/K열에는 적 선언 내용 목록을 위에서부터 채운다.
- 18행: 전장 1~7열 번호 헤더(B18:H18) / "아군 선언 내용" 헤더(J18:K18) — 고정 텍스트.
- 19~27행: 아군 캐릭터 3슬롯 블록. 19~21행이 슬롯0(메인), 22~24행이 슬롯1,
  25~27행이 슬롯2 — 헤더에서 멀어지며 아래로 쌓인다.
- 28행: "아군" 타이틀(B28:H28) — 고정 텍스트, 건드리지 않음.

"전투 이름"(3행, 병합 B3:H3)은 `battle_name`이 주어졌을 때만 갱신한다. 주어지지
않으면(예: 이름 없이 [전투개시]) 기존 텍스트를 그대로 둔다. 위 고정 라벨/헤더
행들은 이 함수가 절대 쓰지 않는 영역이라 병합 해제가 필요 없다 — 병합된 셀도
좌상단 셀 하나에만 값을 쓰면 정상 반영된다.
"""

from typing import TYPE_CHECKING, Optional

import gspread
from gspread.utils import rowcol_to_a1

from battle.core.commands.models import CharacterCommand
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
)
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_character import CombatCharacter

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

# 진영 블록 하나의 높이 (슬롯 3개 x 캐릭터당 3줄)
_FACTION_BLOCK_HEIGHT = CHARACTER_PER_COLUMN * 3  # 9

_HEADER_ROW = 18  # 1~7 열 번호 / "아군 선언 내용" 헤더가 있는 행 (고정 텍스트)

_ENEMY_BLOCK_TOP = _HEADER_ROW - _FACTION_BLOCK_HEIGHT  # 9
_ENEMY_MAIN_ROW_START = _HEADER_ROW - 3  # 15 (슬롯0, 헤더에 바로 인접)
_ENEMY_BLOCK_BOTTOM = _HEADER_ROW - 1  # 17

_ALLY_MAIN_ROW_START = _HEADER_ROW + 1  # 19 (슬롯0, 헤더에 바로 인접)
_ALLY_BLOCK_BOTTOM = _HEADER_ROW + _FACTION_BLOCK_HEIGHT  # 27

_DECLARE_NAME_COL = 10  # J
_DECLARE_CONTENT_COL = 11  # K


def render_public_field_sheet(
    spreadsheet: gspread.Spreadsheet,
    context: "BattlefieldContext",
    round_n: int,
    phase: str,
    enemy_declared: dict[CharacterId, list[CharacterCommand]],
    battle_name: Optional[str] = None,
) -> None:
    ws = spreadsheet.worksheet(_FIELD_SHEET)

    enemy_grid, enemy_declare_grid, notes = _build_faction_block(
        context,
        FactionType.ENEMY,
        main_row_start=_ENEMY_MAIN_ROW_START,
        direction=-1,
        declared=enemy_declared,
    )
    ally_grid, ally_declare_grid, ally_notes = _build_faction_block(
        context,
        FactionType.ALLY,
        main_row_start=_ALLY_MAIN_ROW_START,
        direction=1,
        declared={},
    )
    notes.update(ally_notes)

    updates = []
    if battle_name is not None:
        updates.append({"range": _BATTLE_NAME_CELL, "values": [[battle_name]]})

    updates.extend(
        [
            {"range": _ROUND_CELL, "values": [[f"ROUND {round_n}"]]},
            {"range": _PHASE_CELL, "values": [[phase]]},
            {
                "range": f"B{_ENEMY_BLOCK_TOP}:H{_ENEMY_BLOCK_BOTTOM}",
                "values": enemy_grid,
            },
            {
                "range": f"J{_ENEMY_BLOCK_TOP}:K{_ENEMY_BLOCK_BOTTOM}",
                "values": enemy_declare_grid,
            },
            {
                "range": f"B{_ALLY_MAIN_ROW_START}:H{_ALLY_BLOCK_BOTTOM}",
                "values": ally_grid,
            },
            {
                "range": f"J{_ALLY_MAIN_ROW_START}:K{_ALLY_BLOCK_BOTTOM}",
                "values": ally_declare_grid,
            },
        ]
    )
    ws.batch_update(updates, value_input_option="USER_ENTERED")
    ws.update_notes(notes)


def _build_faction_block(
    context: "BattlefieldContext",
    faction: FactionType,
    *,
    main_row_start: int,
    direction: int,
    declared: dict[CharacterId, list[CharacterCommand]],
) -> tuple[list[list[str]], list[list[str]], dict[str, str]]:
    """진영 블록 하나(9행 x 7열 캐릭터 그리드 + 9행 x 2열 선언 패널)를 조립한다.

    `direction`은 슬롯이 늘어날수록 메인 행(슬롯0)에서 어느 쪽으로 멀어지는지를
    나타낸다 (적군은 -1: 위로, 아군은 +1: 아래로). 반환하는 두 그리드는 모두
    블록의 최상단 행부터 시작하는 상대 좌표라 `batch_update`에 그대로 넘길 수 있다.
    """
    block_top = min(main_row_start, main_row_start + direction * (CHARACTER_PER_COLUMN - 1) * 3)

    grid = [["" for _ in range(_COLUMN_COUNT)] for _ in range(_FACTION_BLOCK_HEIGHT)]
    declare_grid = [["", ""] for _ in range(_FACTION_BLOCK_HEIGHT)]
    notes: dict[str, str] = {}

    for col_idx, column in enumerate(_BATTLEFIELD_COLUMNS):
        slots = context.position_map[faction][column]
        sheet_col = col_idx + 2  # B=2

        for slot in range(CHARACTER_PER_COLUMN):
            name_row = main_row_start + direction * slot * 3
            stats_row = name_row + 1
            buff_row = name_row + 2
            buff_cell = rowcol_to_a1(buff_row, sheet_col)

            char_id = slots.get(slot)
            if char_id is None:
                notes[buff_cell] = ""
                continue

            char = context.characters[char_id]
            grid[name_row - block_top][col_idx] = _format_name_line(char)
            grid[stats_row - block_top][col_idx] = _format_stats_line(char)

            buff_text, note_text = _format_buff_cell(context, char_id)
            grid[buff_row - block_top][col_idx] = buff_text
            notes[buff_cell] = note_text

    row = block_top
    for char_id, commands in declared.items():
        if row > block_top + _FACTION_BLOCK_HEIGHT - 1:
            break
        declare_grid[row - block_top][0] = char_id.name
        declare_grid[row - block_top][1] = " ".join(
            _format_declared_command(command) for command in commands
        )
        row += 1

    return grid, declare_grid, notes


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
    curr_hp = char.status.curr_hp
    max_hp = char.status[CombatStatType.MAX_HP]
    remaining_cost = char.status.remaining_cost
    max_cost = char.status[CombatStatType.COST_PER_TURN]
    return f"{char.id.name}\n[{curr_hp}/{max_hp}] [{remaining_cost}/{max_cost}]"


def _format_stats_line(char: "CombatCharacter") -> str:
    atk = char.status[CombatStatType.ATK]
    attack_range = char.status[CombatStatType.RANGE]
    attack_kind = "마법" if char.status.is_magic_attacker else "물리"
    return f"ATK {atk} · RAN {attack_range}\n{attack_kind} · 마력적응 {_m_res_icon(char)}"


def _m_res_icon(char: "CombatCharacter") -> str:
    """마력적응 아이콘. 저항(유리)은 ▴, 취약(불리)은 ▾, 보통은 ⚬."""
    resistance_value = char.status.m_res.value
    if resistance_value > 0:
        return "▾"
    elif resistance_value < 0:
        return "▴"
    return "⚬"


def _format_buff_cell(
    context: "BattlefieldContext", char_id: CharacterId
) -> tuple[str, str]:
    buffs = context.buff_container.get_buffs_by(char_id, None)
    if not buffs:
        return "", ""

    display_lines = []
    note_lines = []
    for buff in buffs:
        icon = "▾" if buff.is_debuff else "▴"
        label = buff.display_id_label()
        stack_count = buff.stack_count if buff.max_stack is not None else None
        display_lines.append(
            f"{icon} {label}{buff.duration.display_text(stack_count)}"
        )
        description = context.get_buff_data_by_id(buff.id).description
        note_lines.append(f"[{label}] {description}")

    return "\n".join(display_lines), "\n".join(note_lines)
