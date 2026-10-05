from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import CharacterCommand, CommandPart
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.buffs import BuffGivenDamage
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import BuffUid, CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.passive_skill.passive_skill import PassiveSkillWrapperBuff
from battle.objects.skill.effects import SkillEffectAddBuff, SkillEffectDamage
from battle.objects.field_effect.models import FieldEffectSource
from gspread.utils import rowcol_to_a1
from bot.field_sheet_renderer import (
    CHARM_ROW_COUNT,
    EXPORT_BOTTOM_ROW,
    _CHARM_ROW_START,
    _ALLY_BLOCK_BOTTOM,
    _ALLY_MAIN_ROW_START,
    _ENEMY_BLOCK_BOTTOM,
    _ENEMY_BLOCK_TOP,
    _DECLARE_NAME_COL,
    _ENEMY_MAIN_ROW_START,
    _HEADER_ROW,
    _build_faction_block,
    _format_buff_cell,
    _format_field_effect_cell,
    render_public_field_sheet,
)
from helpers import get_test_preset


def test_format_buff_cell_describes_passive_wrapped_buff_without_crashing():
    """패시브 스킬로 부여된 버프는 "버프" 시트가 아니라 "스킬_패시브" 시트
    출신이라 context.get_buff_data_by_id()로 조회하면 KeyError가 난다 —
    필드 시트 렌더링 중 이 조회가 일어나면 안 된다(대신 버프 자신의
    get_description()을 통해 설명을 얻어야 한다)."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    passive_data = PassiveSkillData(
        id="테스트 패시브",
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 1, ValueType.INTEGER, None, None)
        ],
        description="테스트 패시브 설명",
    )
    ctx.buff_container.add_passive_wrapper(
        PassiveSkillWrapperBuff.create(ally_id, passive_data)[0]
    )

    display_text, note_text = _format_buff_cell(ctx, ally_id)

    assert "테스트 패시브" in display_text
    assert "테스트 패시브 설명" in note_text


def test_format_buff_cell_dedupes_passive_with_both_buff_mod_and_effects():
    """패시브 스킬 하나가 buff_mod_event(즉시 수치 보정)와 effects(트리거
    발동 효과)를 동시에 가지면 PassiveSkillWrapperBuff.create()가 역할별로
    나뉜 버프 인스턴스 2개를 반환한다 — 실제 게임 로직상 필요한 분리지만,
    필드 시트에는 같은 패시브 스킬 하나로만 보여야 한다(중복 표시 방지)."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    buff_mod_template = BuffGivenDamage._create_bare(
        id_="이중 역할 패시브",
        uid=BuffUid(ally_id, ally_id, "BuffGivenDamage"),
        given_by=ally_id,
        applied_to=ally_id,
        value=-60,
        value_type=ValueType.PERCENT,
    )
    passive_data = PassiveSkillData(
        id="이중 역할 패시브",
        trigger=PassiveSkillTrigger.ROUND_END,
        target_type=PassiveSkillTargetType.SELF,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=None,
                buff_add_timing=None,
            )
        ],
        description="이중 역할 패시브 설명",
        buff_mod_event=buff_mod_template.create_event(),
    )
    wrappers = PassiveSkillWrapperBuff.create(ally_id, passive_data)
    assert len(wrappers) == 2  # buff_mod 역할 1개 + effects 역할 1개
    for wrapper in wrappers:
        ctx.buff_container.add_passive_wrapper(wrapper)

    display_text, note_text = _format_buff_cell(ctx, ally_id)

    assert display_text.count("이중 역할 패시브") == 1
    assert note_text.count("이중 역할 패시브 설명") == 1


def _make_passive_with_referenced_buff_line(
    ally_id: CharacterId,
) -> PassiveSkillWrapperBuff:
    passive_data = PassiveSkillData(
        id="테스트 패시브",
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 1, ValueType.INTEGER, None, None)
        ],
        description=("설명 본문.\n▸ [보조 버프]: 보조 버프의 개별 설명입니다."),
    )
    return PassiveSkillWrapperBuff.create(ally_id, passive_data)[0]


def test_referenced_buff_line_kept_when_not_yet_granted():
    """패시브 description의 "▸ [버프id]: ..." 줄은, 그 버프가 아직 부여되지
    않은 상태에서는 무엇을 부여하는지 보여주는 미리보기이므로 그대로 남아야
    한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.buff_container.add_passive_wrapper(
        _make_passive_with_referenced_buff_line(ally_id)
    )

    _display_text, note_text = _format_buff_cell(ctx, ally_id)

    assert "▸ [보조 버프]: 보조 버프의 개별 설명입니다." in note_text


def test_referenced_buff_line_stripped_once_buff_is_granted():
    """ "▸ [버프id]: ..." 줄이 가리키는 버프가 실제로 부여되고 나면, 그
    버프가 자기 자신의 note 줄을 따로 갖게 되어 같은 설명이 두 번
    보인다 — 부여된 뒤에는 패시브 쪽 미리보기 줄을 생략해야 한다."""
    ctx = BattlefieldContext(
        buff_dict={
            "보조 버프": BuffData(
                id="보조 버프",
                buff_class_name="BuffGivenDamage",
                duration_turn_value=2,
                duration_count_value=None,
                duration_count_deduct_condition=None,
                value_type=ValueType.PERCENT,
                value=10,
                condition_=None,
                condition_value=None,
                buff_type=BuffType.BUFF,
                description="보조 버프의 개별 설명입니다.",
            )
        },
        skill_dict={},
    )
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.buff_container.add_passive_wrapper(
        _make_passive_with_referenced_buff_line(ally_id)
    )
    ctx.buff_container.add(
        BuffAddData(given_by=ally_id, applied_to=ally_id, buff_id="보조 버프")
    )

    _display_text, note_text = _format_buff_cell(ctx, ally_id)

    assert "▸ [보조 버프]: 보조 버프의 개별 설명입니다." not in note_text
    # "보조 버프" 자신의 note 줄에는 여전히 전체 설명이 정확히 한 번 나와야 한다.
    assert note_text.count("보조 버프의 개별 설명입니다.") == 1


def test_build_faction_block_pushes_remaining_slots_forward_after_removal():
    """같은 열 3슬롯 중 앞(슬롯0)에 있던 캐릭터가 전장에서 제거되면, 남은
    캐릭터들이 슬롯 번호 그대로(1, 2번 슬롯) 렌더링되어 앞자리가 빈칸으로
    보이면 안 된다 — 슬롯 인덱스와 무관하게 남은 순서대로 앞부터 채워야
    한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    column = BattlefieldColumnIndex(0)
    for name in ("A", "B", "C"):
        ctx.add_character(get_test_preset(name), FactionType.ALLY, column)
    ctx.remove_character(CharacterId("A"))  # 슬롯0을 비움 → {1: B, 2: C}

    grid, _declare_text, _notes, _merges = _build_faction_block(
        ctx,
        FactionType.ALLY,
        main_row_start=_ALLY_MAIN_ROW_START,
        direction=1,
        declared={},
    )

    assert "B" in grid[0][0]
    assert "C" in grid[3][0]
    assert grid[6][0] == ""


def test_build_faction_block_joins_declared_commands_into_single_text():
    """선언 내용은 더 이상 행별 그리드가 아니라, 적이 아무리 많아도 병합된
    셀 하나에 "이름 [커맨드]" 줄을 `\\n`으로 이어붙인 문자열 하나로
    반환되어야 한다(그리드였다면 슬롯 수를 넘는 적이 있을 때 구조가
    깨졌다)."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    enemy_ids = []
    for i in range(5):
        name = f"적{i}"
        column = BattlefieldColumnIndex(i // 3)  # 열당 최대 3명 제한 회피
        ctx.add_character(get_test_preset(name), FactionType.ENEMY, column)
        enemy_ids.append(CharacterId(name))

    declared = {
        enemy_id: [
            CharacterCommand(
                user_id=enemy_id,
                parts=[
                    CommandPart(
                        type_=ActionType.ATTACK, targets=[CharacterId("아군 1")]
                    )
                ],
            )
        ]
        for enemy_id in enemy_ids
    }

    _grid, declare_text, _notes, _merges = _build_faction_block(
        ctx,
        FactionType.ENEMY,
        main_row_start=_ALLY_MAIN_ROW_START,
        direction=1,
        declared=declared,
    )

    lines = declare_text.split("\n")
    assert len(lines) == 5
    assert lines[0] == "적0 [공격/아군 1]"
    assert lines[4] == "적4 [공격/아군 1]"


def _context_with_field_effect(description: str = "전장이 불타오른다.") -> tuple:
    """필드 효과 하나가 걸린 전장과 그 효과 id를 돌려준다."""
    effect_id = "FieldEffect"
    ctx = BattlefieldContext(
        buff_dict={},
        skill_dict={},
        passive_skill_dict={
            effect_id: PassiveSkillData(
                id=effect_id,
                trigger=PassiveSkillTrigger.ROUND_START,
                target_type=PassiveSkillTargetType.FIELD_ALL,
                effects=[],
                description=description,
            )
        },
    )
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    return ctx, effect_id


def test_field_effect_cell_says_none_when_nothing_is_active():
    """빈 칸으로 두면 "아직 렌더링되지 않은 것"과 구분되지 않는다."""
    ctx, _ = _context_with_field_effect()

    display_text, note_text = _format_field_effect_cell(ctx)

    assert display_text == "없음"
    assert note_text == ""


def test_field_effect_cell_lists_active_effects_with_source():
    ctx, effect_id = _context_with_field_effect()
    ctx.add_field_effect(effect_id, FieldEffectSource.SKILL, "시전자_1")

    display_text, _ = _format_field_effect_cell(ctx)

    assert display_text == f"{effect_id}[시전자_1]"


def test_field_effect_cell_joins_several_on_one_line():
    """한 행짜리 칸이라 줄을 나누면 두 번째부터 잘린다."""
    ctx, effect_id = _context_with_field_effect()
    other_id = "FieldEffect2"
    ctx._passive_skill_dictionary[other_id] = PassiveSkillData(
        id=other_id,
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=PassiveSkillTargetType.FIELD_ALL,
        effects=[],
        description="두 번째 효과 설명",
    )
    ctx.add_field_effect(effect_id, FieldEffectSource.ADMIN)
    ctx.add_field_effect(other_id, FieldEffectSource.SKILL, "시전자_2")

    display_text, note_text = _format_field_effect_cell(ctx)

    assert display_text == f"{effect_id}[시스템] · {other_id}[시전자_2]"
    assert "\n" not in display_text
    # 설명은 줄을 나눠 메모에 담는다 — 메모에는 높이 제약이 없다.
    assert note_text.count("\n") == 1


def test_field_effect_description_goes_to_the_note():
    """그리드가 좁아 본문에 설명까지 넣으면 이름이 밀린다 — 버프 칸과 같이
    설명은 셀 메모에 담는다."""
    ctx, effect_id = _context_with_field_effect("전장이 불타오른다.")
    ctx.add_field_effect(effect_id, FieldEffectSource.ADMIN)

    display_text, note_text = _format_field_effect_cell(ctx)

    assert "전장이 불타오른다." not in display_text
    assert note_text == f"[{effect_id}] 전장이 불타오른다."


def test_layout_rows_follow_the_header_row():
    """시트 위쪽에 행이 늘고 줄 때 _HEADER_ROW 하나만 맞추면 되도록 나머지
    행 상수는 전부 여기서 파생된다 — 실제 시트와 어긋나면 격자가 통째로
    한 칸씩 밀려 쓰인다."""
    assert _ENEMY_BLOCK_TOP == _HEADER_ROW - 9
    assert _ENEMY_MAIN_ROW_START == _HEADER_ROW - 3
    assert _ENEMY_BLOCK_BOTTOM == _HEADER_ROW - 1
    assert _CHARM_ROW_START == _HEADER_ROW + 1
    assert _ALLY_MAIN_ROW_START == _HEADER_ROW + 1 + CHARM_ROW_COUNT
    assert _ALLY_BLOCK_BOTTOM == _ALLY_MAIN_ROW_START + 8
    # 이미지 캡처가 아군 블록 아래(“아군” 띠 + 여백)까지 담는지.
    assert EXPORT_BOTTOM_ROW > _ALLY_BLOCK_BOTTOM


def test_multi_column_character_is_written_once_and_merged():
    """행도 걸친 열 전부에서 같아야 한다 — 열마다 따로 앞으로 당기면 덩치가
    끊겨 보인다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    # 0열에만 다른 적이 하나 있어, 열마다 따로 앞으로 당기면 0열에서는 둘째
    # 줄, 1열에서는 첫째 줄에 놓여 어긋나는 배치다.
    ctx.add_character(
        get_test_preset("선점"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("거대적", span=2), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    grid, _declare_text, _notes, merges = _build_faction_block(
        ctx,
        FactionType.ENEMY,
        main_row_start=_ENEMY_MAIN_ROW_START,
        direction=-1,
        declared={},
    )

    name_rows = [
        index for index, row in enumerate(grid) if any("거대적" in cell for cell in row)
    ]
    assert len(name_rows) == 1
    # 왼쪽 끝(B=0번째) 칸에만 값이 들어가고 오른쪽 칸은 비어 있다.
    assert "거대적" in grid[name_rows[0]][0]
    assert grid[name_rows[0]][1] == ""

    # 이름/스탯/버프 세 줄이 B~C(2~3열)로 병합된다.
    assert len(merges) == 3
    assert {(first, last) for _row, first, last in merges} == {(2, 3)}
    merged_rows = sorted(row for row, _first, _last in merges)
    assert merged_rows == list(range(merged_rows[0], merged_rows[0] + 3))


def test_single_column_character_is_not_merged():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("적 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    _grid, _declare_text, _notes, merges = _build_faction_block(
        ctx,
        FactionType.ENEMY,
        main_row_start=_ENEMY_MAIN_ROW_START,
        direction=-1,
        declared={},
    )

    assert merges == []


class _FakeFieldWorksheet:
    id = 4242
    title = "필드"


class _RecordingFieldSpreadsheet:
    """공개 "필드" 시트 쓰기를 기록하는 가짜 스프레드시트. 값·메모·병합을
    한 번의 batch_update로 보내는지 확인하는 데 쓴다."""

    def __init__(self):
        self.ws = _FakeFieldWorksheet()
        self.bodies: list[dict] = []

    def worksheet(self, name):
        assert name == "필드"
        return self.ws

    def batch_update(self, body):
        self.bodies.append(body)


def _written_cells(body: dict) -> dict[str, tuple[str, str | None]]:
    """updateCells 요청들을 A1 → (값, 메모)로 펼친다."""
    cells: dict[str, tuple[str, str | None]] = {}
    for request in body["requests"]:
        update = request.get("updateCells")
        if update is None:
            continue
        grid = update["range"]
        for row_offset, row in enumerate(update["rows"]):
            for col_offset, cell in enumerate(row["values"]):
                a1 = rowcol_to_a1(
                    grid["startRowIndex"] + 1 + row_offset,
                    grid["startColumnIndex"] + 1 + col_offset,
                )
                value = cell.get("userEnteredValue", {}).get("stringValue", "")
                cells[a1] = (value, cell.get("note"))
    return cells


def _render_once(**kwargs) -> _RecordingFieldSpreadsheet:
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("적 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(1)
    )
    spreadsheet = _RecordingFieldSpreadsheet()
    render_public_field_sheet(
        spreadsheet,
        ctx,
        round_n=3,
        phase="아군 행동",
        enemy_declared={},
        **kwargs,
    )
    return spreadsheet


def test_render_public_field_sheet_sends_one_api_call():
    spreadsheet = _render_once()

    assert len(spreadsheet.bodies) == 1

    cells = _written_cells(spreadsheet.bodies[0])
    assert cells["B4"][0] == "ROUND 3"
    assert cells["D6"][0] == "아군 행동"
    assert cells["D7"][0] == "없음"

    # 진영 격자는 각 블록의 슬롯0 행에 이름이 들어간다.
    enemy_names = [
        value
        for a1, (value, _) in cells.items()
        if a1.startswith("B") and "적 1" in value
    ]
    ally_names = [
        value
        for a1, (value, _) in cells.items()
        if a1.startswith("C") and "아군 1" in value
    ]
    assert enemy_names and ally_names


def test_render_public_field_sheet_folds_initial_merges_into_the_same_call():
    spreadsheet = _render_once(ensure_merged=True)

    assert len(spreadsheet.bodies) == 1
    merges = [
        request["mergeCells"]
        for request in spreadsheet.bodies[0]["requests"]
        if "mergeCells" in request
    ]
    declare_merges = [
        merge
        for merge in merges
        if merge["range"]["startColumnIndex"] == _DECLARE_NAME_COL - 1
    ]
    assert len(declare_merges) == 2


def test_render_public_field_sheet_clears_stale_notes_in_the_grid():
    spreadsheet = _render_once()
    cells = _written_cells(spreadsheet.bodies[0])

    # 아무도 없는 7열(H) 적군 블록 칸.
    empty_cell = rowcol_to_a1(_ENEMY_MAIN_ROW_START + 2, 8)
    assert cells[empty_cell] == ("", "")


def test_render_public_field_sheet_merges_multi_column_enemy_in_one_call():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("거대적", span=3), FactionType.ENEMY, BattlefieldColumnIndex(1)
    )
    spreadsheet = _RecordingFieldSpreadsheet()

    render_public_field_sheet(
        spreadsheet,
        ctx,
        round_n=1,
        phase="적 선언",
        enemy_declared={},
    )

    assert len(spreadsheet.bodies) == 1
    requests = spreadsheet.bodies[0]["requests"]

    # 적군 격자(B~H)를 먼저 풀고 나서 병합해야 이전 범위가 남지 않는다.
    unmerge_indexes = [
        index
        for index, request in enumerate(requests)
        if "unmergeCells" in request
        and request["unmergeCells"]["range"]["startRowIndex"] == _ENEMY_BLOCK_TOP - 1
    ]
    assert len(unmerge_indexes) == 1

    # 2열(C)에 선 span 3짜리라 이름/스탯/버프 세 줄이 C~E로 병합된다.
    enemy_merges = [
        (index, request["mergeCells"]["range"])
        for index, request in enumerate(requests)
        if "mergeCells" in request
        and request["mergeCells"]["range"]["startColumnIndex"] == 2
        and request["mergeCells"]["range"]["endColumnIndex"] == 5
    ]
    assert len(enemy_merges) == 3
    assert all(index > unmerge_indexes[0] for index, _range in enemy_merges)

    # 값은 왼쪽 끝 열(C)에만 들어가고 나머지는 비어 있다.
    cells = _written_cells(spreadsheet.bodies[0])
    name_cells = {a1 for a1, (value, _) in cells.items() if "거대적" in value}
    assert len(name_cells) == 1
    assert next(iter(name_cells)).startswith("C")
