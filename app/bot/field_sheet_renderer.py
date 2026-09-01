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
  J9:K17은 병합된 셀 하나다 — 적 선언 내용을 "이름 [커맨드]" 줄 단위로 `\n`을
  이어붙여 그 한 셀(J9)에 통째로 쓴다. 적 수가 많아도(예: 20기 이상) 행 수
  제약 없이 한 셀 안에서 줄바꿈으로만 늘어나므로 그리드 구조가 깨지지 않는다.
- 18행: 전장 1~7열 번호 헤더(B18:H18) / "아군 선언 내용" 헤더(J18:K18) — 고정 텍스트.
- 19~27행: 아군 캐릭터 3슬롯 블록. 19~21행이 슬롯0(메인), 22~24행이 슬롯1,
  25~27행이 슬롯2 — 헤더에서 멀어지며 아래로 쌓인다. J19:K27도 마찬가지로
  병합된 셀 하나(J19)에 아군 선언 내용을 `\n`으로 이어붙인다.
- 28행: "아군" 타이틀(B28:H28) — 고정 텍스트, 건드리지 않음.

J9:K17/J19:K27 병합은 `ensure_merged=True`로 호출했을 때만 수행한다(구조적
변경이라 값 쓰기와 별개의 API 호출이 필요해 매 렌더링마다 부르면 낭비다) —
전투 시작 시 한 번만 병합해 두면 이후에는 이미 병합된 상태가 시트에
그대로 남아 있으므로, 매 라운드/커맨드마다 다시 병합할 필요가 없다.

"전투 이름"(3행, 병합 B3:H3)은 `battle_name`이 주어졌을 때만 갱신한다. 주어지지
않으면(예: 이름 없이 [전투개시]) 기존 텍스트를 그대로 둔다. 위 고정 라벨/헤더
행들은 이 함수가 절대 쓰지 않는 영역이라 병합 해제가 필요 없다 — 병합된 셀도
좌상단 셀 하나에만 값을 쓰면 정상 반영된다.
"""

import re
from typing import TYPE_CHECKING, Optional

import gspread
from gspread.utils import ValueInputOption, rowcol_to_a1

from battle.core.commands.models import CharacterCommand
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
)
from battle.objects.models import CharacterId
from battle.objects.passive_skill.passive_skill import PassiveSkillWrapperBuff
from bot.sheet_cache import SheetCache

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

_DECLARE_NAME_COL = 10  # J (병합된 선언 내용 셀의 좌상단 — J9:K17 / J19:K27)


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

    if ensure_merged:
        ws.merge_cells(f"J{_ENEMY_BLOCK_TOP}:K{_ENEMY_BLOCK_BOTTOM}")
        ws.merge_cells(f"J{_ALLY_MAIN_ROW_START}:K{_ALLY_BLOCK_BOTTOM}")

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
                "range": rowcol_to_a1(_ENEMY_BLOCK_TOP, _DECLARE_NAME_COL),
                "values": [[enemy_declare_text]],
            },
            {
                "range": f"B{_ALLY_MAIN_ROW_START}:H{_ALLY_BLOCK_BOTTOM}",
                "values": ally_grid,
            },
            {
                "range": rowcol_to_a1(_ALLY_MAIN_ROW_START, _DECLARE_NAME_COL),
                "values": [[ally_declare_text]],
            },
        ]
    )
    ws.batch_update(updates, value_input_option=ValueInputOption.user_entered)
    ws.update_notes(notes)


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

    for col_idx, column in enumerate(_BATTLEFIELD_COLUMNS):
        slots = context.position_map[faction][column]
        # position_map은 슬롯 인덱스(0~2)를 키로 갖는데, 캐릭터가 전장에서
        # 빠지면 그 슬롯 키만 pop되고 나머지 슬롯은 그대로 남는다(예: 슬롯0이
        # 빠지면 {1: b, 2: c}). 그 인덱스를 그대로 행에 매핑하면 필드
        # 시트에서 헤더와 가장 가까운 "앞" 칸이 빈칸으로 보이게 된다 —
        # 실제 슬롯 번호와 무관하게 남아 있는 순서대로 앞(main_row_start)부터
        # 채워 빈칸이 생기지 않게 한다.
        occupants = [slots[i] for i in sorted(slots.keys())]
        sheet_col = col_idx + 2  # B=2

        for slot in range(CHARACTER_PER_COLUMN):
            name_row = main_row_start + direction * slot * 3
            stats_row = name_row + 1
            buff_row = name_row + 2
            buff_cell = rowcol_to_a1(buff_row, sheet_col)

            if slot >= len(occupants):
                notes[buff_cell] = ""
                continue
            char_id = occupants[slot]

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


# 패시브 스킬 등의 description은 "▸ [버프id]: 설명" 형태로 자신이 부여하는
# 다른 버프를 미리 문서화해 둔 줄을 포함할 수 있다(예: "...부여한다.\n▸
# [우월감]: 버프. 적에게 주는 대미지가 10% 증가한다."). 그 버프가 아직
# 부여되지 않은 상태에서는 유용한 미리보기지만, 실제로 부여되고 나면 그
# 버프가 필드 시트에 자기 자신의 note 줄을 따로 갖게 되어 같은 설명이
# 두 번 보인다.
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
        # 패시브 스킬 하나가 buff_mod_event(즉시 적용 수치 보정)와 effects(트리거
        # 발동 효과)를 동시에 가지면 PassiveSkillWrapperBuff.create()가 역할별로
        # 나뉜 버프 인스턴스를 여러 개 등록한다(passive_skill.py 참고) — 게임
        # 로직상으로는 각자 다른 타이밍에 독립적으로 발동해야 해서 반드시
        # 그렇게 나뉘어 있어야 하지만, 사람이 보는 필드 시트에는 같은 패시브
        # 스킬 하나로만 보여야 하므로 같은 라벨의 두 번째 이후 인스턴스는
        # 건너뛴다.
        if isinstance(buff, PassiveSkillWrapperBuff):
            if label in seen_passive_labels:
                continue
            seen_passive_labels.add(label)
        icon = "▾" if buff.is_debuff else "▴"
        stack_count = buff.stack_count if buff.max_stack is not None else None
        display_lines.append(f"{icon} {label}{buff.duration.display_text(stack_count)}")
        description = _strip_lines_for_already_present_buffs(
            buff.get_description(context), active_buff_ids
        )
        note_lines.append(f"[{label}] {description}")

    return "\n".join(display_lines), "\n".join(note_lines)
