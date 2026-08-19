import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import gspread  # noqa: E402

from battle.core.battlefield_context import BattlefieldContext  # noqa: E402
from battle.core.commands.models import CharacterCommand, CommandPart  # noqa: E402
from battle.objects.define import ActionType  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.skill.models import SkillData  # noqa: E402
from bot.load_data import (  # noqa: E402
    get_character_gold,
    mark_enemy_skill_revealed,
    reveal_declared_enemy_skills,
    update_character_curr_hp,
    update_character_daily_quest_status_id,
    update_character_quest_date,
)
from bot.sheet_cache import SheetCache  # noqa: E402


class _FakeWorksheet:
    def __init__(self, rows: list[list]):
        self.rows = rows  # 헤더 포함, get_values() 형식
        self.written: list[tuple[int, int, object]] = []
        self.update_calls: list[dict] = []
        self.get_values_call_count = 0

    def get_values(self, value_render_option=None, pad_values=True):
        self.get_values_call_count += 1
        return self.rows

    def update_cell(self, row, col, value):
        self.written.append((row, col, value))

    def update(
        self, values, range_name=None, raw=True, value_input_option=None, **kwargs
    ):
        row, col = gspread.utils.a1_to_rowcol(range_name)
        value = values[0][0]
        self.written.append((row, col, value))
        self.update_calls.append(
            {
                "row": row,
                "col": col,
                "value": value,
                "raw": raw,
                "value_input_option": value_input_option,
            }
        )


class _FakeSpreadsheet:
    def __init__(self, sheets: dict[str, list[list]]):
        self._sheets = {name: _FakeWorksheet(rows) for name, rows in sheets.items()}
        self.id = "fake-id"
        self.client = None
        self.fetch_sheet_metadata_call_count = 0

    def worksheet(self, name):
        if name not in self._sheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._sheets[name]

    def fetch_sheet_metadata(self):
        self.fetch_sheet_metadata_call_count += 1
        return {"sheets": [{"properties": {"title": name}} for name in self._sheets]}


def _make_cache(spreadsheet: _FakeSpreadsheet) -> SheetCache:
    return SheetCache(
        spreadsheet,
        worksheet_factory=lambda properties: spreadsheet._sheets[properties["title"]],
    )


def test_update_character_curr_hp_writes_matching_row():
    rows = [["name", "curr_hp"], ["아군1", "50"], ["아군2", "30"]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_curr_hp(spreadsheet, "아군2", 10)

    ws = spreadsheet.worksheet("캐릭터")
    assert (3, 2, 10) in ws.written


def test_update_character_curr_hp_falls_back_to_enemy_sheet():
    char_rows = [["name", "curr_hp"], ["아군1", "50"]]
    enemy_rows = [["name", "curr_hp"], ["고블린", "20"]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": char_rows, "에너미": enemy_rows})

    update_character_curr_hp(spreadsheet, "고블린", 5)

    assert (2, 2, 5) in spreadsheet.worksheet("에너미").written
    assert spreadsheet.worksheet("캐릭터").written == []


def test_update_character_curr_hp_raises_when_not_found():
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name", "curr_hp"], ["아군1", "50"]]})

    try:
        update_character_curr_hp(spreadsheet, "없는캐릭터", 10)
        assert False, "예외가 발생해야 한다"
    except RuntimeError:
        pass


def test_update_character_curr_hp_with_cache_shares_metadata_and_invalidates():
    """cache를 넘기면 "캐릭터"/"에너미" 조회가 메타데이터를 공유해야 하고,
    쓰기 후에는 실제로 쓴 시트의 캐시 값이 무효화되어 다음 읽기가 최신
    값을 다시 읽어와야 한다."""
    char_rows = [["name", "curr_hp"], ["아군1", "50"]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": char_rows})
    cache = _make_cache(spreadsheet)

    update_character_curr_hp(spreadsheet, "아군1", 33, cache=cache)

    assert spreadsheet.fetch_sheet_metadata_call_count == 1
    ws = spreadsheet.worksheet("캐릭터")
    assert (2, 2, 33) in ws.written

    # 쓰기 직후 다시 읽으면(캐시가 무효화됐으므로) 최신 get_values 호출이 발생해야 한다.
    before = ws.get_values_call_count
    cache.get_all_values("캐릭터")
    assert ws.get_values_call_count == before + 1


def test_update_character_quest_date_writes_matching_row():
    rows = [
        ["name", "gold", "daily_quest_date"],
        ["아군1", "5", "2026-01-01"],
        ["아군2", "0", ""],
    ]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_quest_date(spreadsheet, "아군2", "2026-08-03")

    ws = spreadsheet.worksheet("캐릭터")
    assert (3, 3, "2026-08-03") in ws.written


def test_update_character_quest_date_does_not_write_gold():
    """ "캐릭터" 시트의 gold는 봇이 직접 갱신하지 않는다 — 소지금 변동은
    "가계부" 시트 기록만으로 관리한다."""
    rows = [
        ["name", "gold", "daily_quest_date"],
        ["아군1", "5", "2026-01-01"],
    ]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_quest_date(spreadsheet, "아군1", "2026-08-03")

    ws = spreadsheet.worksheet("캐릭터")
    assert all(col != 2 for _row, col, _value in ws.written)


def test_update_character_quest_date_stores_date_as_raw_string():
    """daily_quest_date는 handle_daily_quest_start()에서 문자열 그대로
    재비교된다 — update_cell()의 고정 USER_ENTERED로 쓰면 "YYYY-MM-DD" 형식의
    문자열이 Sheets에 의해 날짜 타입(내부 시리얼 넘버)으로 자동 변환되고,
    이후 UNFORMATTED_VALUE로 다시 읽으면 그 시리얼 넘버 문자열이 반환되어
    "오늘 이미 했음" 비교가 영원히 거짓이 되며 1일 1회 제한이 무력화된다.
    RAW(raw=True, 기본값)로 저장해 이 자동 변환을 막아야 한다."""
    rows = [
        ["name", "gold", "daily_quest_date"],
        ["아군1", "0", ""],
    ]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_quest_date(spreadsheet, "아군1", "2026-08-03")

    ws = spreadsheet.worksheet("캐릭터")
    date_call = next(c for c in ws.update_calls if c["col"] == 3)
    assert date_call["value"] == "2026-08-03"
    assert date_call["raw"] is True


def test_update_character_quest_date_raises_when_not_found():
    spreadsheet = _FakeSpreadsheet(
        {"캐릭터": [["name", "gold", "daily_quest_date"], ["아군1", "0", ""]]}
    )

    try:
        update_character_quest_date(spreadsheet, "없는캐릭터", "2026-08-03")
        assert False, "예외가 발생해야 한다"
    except RuntimeError:
        pass


def test_update_character_quest_date_also_clears_status_id_when_present():
    """의뢰 완수 시 daily_quest_status_id도 함께 비워야 재기동 복원 대상에서
    빠진다."""
    rows = [
        ["name", "gold", "daily_quest_date", "daily_quest_status_id"],
        ["아군1", "0", "", "123456"],
    ]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_quest_date(spreadsheet, "아군1", "2026-08-03")

    ws = spreadsheet.worksheet("캐릭터")
    assert (2, 3, "2026-08-03") in ws.written
    assert (2, 4, "") in ws.written


def test_update_character_quest_date_skips_status_id_when_column_missing():
    """기존(daily_quest_status_id 컬럼이 없는) 캐릭터 시트에서도
    daily_quest_date 갱신 자체는 그대로 동작해야 한다."""
    rows = [["name", "gold", "daily_quest_date"], ["아군1", "0", ""]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_quest_date(spreadsheet, "아군1", "2026-08-03")

    ws = spreadsheet.worksheet("캐릭터")
    assert (2, 3, "2026-08-03") in ws.written
    assert len(ws.written) == 1


def test_get_character_gold_reads_matching_row():
    rows = [
        ["name", "gold", "daily_quest_date"],
        ["아군1", "5", ""],
        ["아군2", "42", ""],
    ]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    assert get_character_gold(spreadsheet, "아군2") == 42


def test_get_character_gold_raises_when_not_found():
    spreadsheet = _FakeSpreadsheet({"캐릭터": [["name", "gold"], ["아군1", "5"]]})

    try:
        get_character_gold(spreadsheet, "없는캐릭터")
        assert False, "예외가 발생해야 한다"
    except RuntimeError:
        pass


def test_get_character_gold_reads_via_cache():
    """캐시를 넘기면 캐시가 반환하는 값(가계부 기록 후 invalidate로 새로
    읽힌 값 포함)을 그대로 사용해야 한다."""
    rows = [["name", "gold"], ["아군1", "7"]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})
    cache = _make_cache(spreadsheet)

    assert get_character_gold(spreadsheet, "아군1", cache=cache) == 7

    # gold 수식이 재계산된 것을 흉내낸다: 시트 원본이 바뀐 뒤 캐시를
    # 무효화하면 다음 조회가 새 값을 읽어야 한다.
    spreadsheet.worksheet("캐릭터").rows[1][1] = "8"
    cache.invalidate("캐릭터")

    assert get_character_gold(spreadsheet, "아군1", cache=cache) == 8


def test_update_character_daily_quest_status_id_writes_matching_row():
    rows = [
        ["name", "daily_quest_status_id"],
        ["아군1", ""],
        ["아군2", ""],
    ]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_daily_quest_status_id(spreadsheet, "아군2", "999")

    ws = spreadsheet.worksheet("캐릭터")
    assert (3, 2, "999") in ws.written


def test_update_character_daily_quest_status_id_noop_when_column_missing():
    """daily_quest_status_id 컬럼 자체가 없는 시트에서는 조용히 아무 것도
    쓰지 않아야 한다(기존 [의뢰] 흐름을 깨면 안 됨)."""
    rows = [["name", "gold"], ["아군1", "0"]]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_daily_quest_status_id(spreadsheet, "아군1", "999")

    assert spreadsheet.worksheet("캐릭터").written == []


def test_mark_enemy_skill_revealed_writes_true_to_matching_row():
    rows = [["id", "is_revealed"], ["스킬_1", ""], ["스킬_2", "TRUE"]]
    spreadsheet = _FakeSpreadsheet({"스킬_에너미": rows})

    mark_enemy_skill_revealed(spreadsheet, "스킬_1")

    assert (2, 2, True) in spreadsheet.worksheet("스킬_에너미").written


def test_mark_enemy_skill_revealed_noop_when_column_missing():
    """is_revealed 컬럼이 아직 시트에 추가되기 전에도 예외 없이 넘어가야 한다."""
    rows = [["id"], ["스킬_1"]]
    spreadsheet = _FakeSpreadsheet({"스킬_에너미": rows})

    mark_enemy_skill_revealed(spreadsheet, "스킬_1")

    assert spreadsheet.worksheet("스킬_에너미").written == []


def test_mark_enemy_skill_revealed_noop_when_sheet_missing():
    """'스킬_에너미' 시트 자체가 없어도 WorksheetNotFound를 삼키고 조용히 넘어가야 한다."""
    spreadsheet = _FakeSpreadsheet({})

    mark_enemy_skill_revealed(spreadsheet, "스킬_1")


def _skill_command(skill_id: str) -> CharacterCommand:
    return CharacterCommand(
        user_id=CharacterId("적군 1"),
        parts=[CommandPart(type_=ActionType.SKILL, skill_id=skill_id, targets=[])],
    )


def test_reveal_declared_enemy_skills_updates_context_and_sheet():
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[],
        description="",
        revealed=False,
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})
    rows = [["id", "is_revealed"], ["스킬_1", ""]]
    spreadsheet = _FakeSpreadsheet({"스킬_에너미": rows})

    reveal_declared_enemy_skills(spreadsheet, ctx, _skill_command("스킬_1"))

    assert ctx.get_skill_data_by_id("스킬_1").revealed is True
    assert (2, 2, True) in spreadsheet.worksheet("스킬_에너미").written


def test_reveal_declared_enemy_skills_skips_already_revealed_skill():
    """이미 공개된 스킬은 시트에 다시 쓰지 않는다."""
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[],
        description="",
        revealed=True,
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})
    rows = [["id", "is_revealed"], ["스킬_1", "TRUE"]]
    spreadsheet = _FakeSpreadsheet({"스킬_에너미": rows})

    reveal_declared_enemy_skills(spreadsheet, ctx, _skill_command("스킬_1"))

    assert spreadsheet.worksheet("스킬_에너미").written == []


def test_reveal_declared_enemy_skills_reads_sheet_once_for_multiple_skills():
    """한 커맨드(하이픈으로 이어붙인 복수 스킬)에 아직 공개되지 않은 스킬이
    여러 개 있어도 '스킬_에너미' 시트는 한 번만 읽어야 한다 — 스킬마다 개별
    write-back 후 캐시를 무효화하면 뒤이은 스킬이 매번 재조회하게 된다."""
    skill_a = SkillData(
        id="스킬_A",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[],
        description="",
        revealed=False,
    )
    skill_b = SkillData(
        id="스킬_B",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[],
        description="",
        revealed=False,
    )
    ctx = BattlefieldContext(
        buff_dict={}, skill_dict={"스킬_A": skill_a, "스킬_B": skill_b}
    )
    command = CharacterCommand(
        user_id=CharacterId("적군 1"),
        parts=[
            CommandPart(type_=ActionType.SKILL, skill_id="스킬_A", targets=[]),
            CommandPart(type_=ActionType.SKILL, skill_id="스킬_B", targets=[]),
        ],
    )
    rows = [["id", "is_revealed"], ["스킬_A", ""], ["스킬_B", ""]]
    spreadsheet = _FakeSpreadsheet({"스킬_에너미": rows})
    cache = _make_cache(spreadsheet)

    reveal_declared_enemy_skills(spreadsheet, ctx, command, cache=cache)

    ws = spreadsheet.worksheet("스킬_에너미")
    assert ws.get_values_call_count == 1
    assert (2, 2, True) in ws.written
    assert (3, 2, True) in ws.written
    assert ctx.get_skill_data_by_id("스킬_A").revealed is True
    assert ctx.get_skill_data_by_id("스킬_B").revealed is True
