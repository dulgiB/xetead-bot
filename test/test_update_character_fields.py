import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import gspread  # noqa: E402

from battle.core.battlefield_context import BattlefieldContext  # noqa: E402
from battle.core.commands.models import CharacterCommand, CommandPart  # noqa: E402
from battle.objects.define import ActionType  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.skill.models import SkillData  # noqa: E402
from bot.load_data import (  # noqa: E402
    mark_enemy_skill_revealed,
    reveal_declared_enemy_skills,
    update_character_curr_hp,
    update_character_gold_and_quest_date,
)
from bot.sheet_cache import SheetCache  # noqa: E402


class _FakeWorksheet:
    def __init__(self, rows: list[list]):
        self.rows = rows  # 헤더 포함, get_values() 형식
        self.written: list[tuple[int, int, object]] = []
        self.get_values_call_count = 0

    def get_values(self, value_render_option=None, pad_values=True):
        self.get_values_call_count += 1
        return self.rows

    def update_cell(self, row, col, value):
        self.written.append((row, col, value))


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


def test_update_character_gold_and_quest_date_writes_matching_row():
    rows = [
        ["name", "gold", "daily_quest_date"],
        ["아군1", "5", "2026-01-01"],
        ["아군2", "0", ""],
    ]
    spreadsheet = _FakeSpreadsheet({"캐릭터": rows})

    update_character_gold_and_quest_date(spreadsheet, "아군2", 1, "2026-08-03")

    ws = spreadsheet.worksheet("캐릭터")
    assert (3, 2, 1) in ws.written
    assert (3, 3, "2026-08-03") in ws.written


def test_update_character_gold_and_quest_date_raises_when_not_found():
    spreadsheet = _FakeSpreadsheet(
        {"캐릭터": [["name", "gold", "daily_quest_date"], ["아군1", "0", ""]]}
    )

    try:
        update_character_gold_and_quest_date(spreadsheet, "없는캐릭터", 1, "2026-08-03")
        assert False, "예외가 발생해야 한다"
    except RuntimeError:
        pass


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
        id="스킬_A", target_rule="SkillTargetRuleNamed", target_count=1, cost=0,
        effects=[], description="", revealed=False,
    )
    skill_b = SkillData(
        id="스킬_B", target_rule="SkillTargetRuleNamed", target_count=1, cost=0,
        effects=[], description="", revealed=False,
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_A": skill_a, "스킬_B": skill_b})
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
