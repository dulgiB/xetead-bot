from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from helpers import get_test_preset
from spreadsheets.inventory import Inventory


def _ally_action_manager(ctx) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


def test_build_log_entries_records_damage(context_with_damage_skill):
    ctx = context_with_damage_skill
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="강타"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))

    before = len(ctx.results)
    cmd = parse_character_command(CharacterId("아군 1"), "[스킬/강타/적군 1]")
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    assert len(entries) == 1
    assert entries[0].target_name == "적군 1"
    assert entries[0].result.startswith("대미지 ")
    assert entries[0].roll_display is not None


def test_build_log_entries_records_heal(context_with_heal_skill):
    ctx = context_with_heal_skill
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="회복", initial_hp=50),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 2", initial_hp=50), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    before = len(ctx.results)
    cmd = parse_character_command(CharacterId("아군 1"), "[스킬/회복/아군 2]")
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    assert len(entries) == 1
    assert entries[0].target_name == "아군 2"
    assert entries[0].result == "회복 10"


def test_build_log_entries_records_buff_add(context_with_atk_buff_skill):
    ctx = context_with_atk_buff_skill
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="공격 보조"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(1))

    before = len(ctx.results)
    cmd = parse_character_command(CharacterId("아군 1"), "[스킬/공격 보조/아군 2]")
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    assert len(entries) == 1
    assert entries[0].target_name == "아군 2"
    assert "[공격력 증가] 부여" == entries[0].result
    assert entries[0].roll_display is None


def test_inventory_grant_updates_existing_row():
    inv = Inventory({("아군 1", "포션"): 1})
    inv.grant("아군 1", "포션", 2)
    assert inv.get_count("아군 1", "포션") == 3


def test_inventory_grant_creates_new_entry_when_absent():
    inv = Inventory({})
    inv.grant("아군 2", "포션", 1)
    assert inv.get_count("아군 2", "포션") == 1


class _FakeCell:
    def __init__(self, value):
        self.value = value


class _FakeWorksheet:
    """append_row 호출을 기록하는 최소 gspread Worksheet 모사체."""

    def __init__(self, header, rows):
        self._header = header
        self._rows = rows
        self.appended: list[list] = []

    def get_all_records(self):
        return [dict(zip(self._header, row)) for row in self._rows]

    def row_values(self, _row_num):
        return self._header

    def update_cell(self, row_idx, col_idx, value):
        self._rows[row_idx - 2][col_idx - 1] = value

    def append_row(self, row, value_input_option=None):
        self.appended.append(row)
        self._rows.append(row)


class _FakeSpreadsheet:
    def __init__(self, worksheet):
        self._worksheet = worksheet

    def worksheet(self, _name):
        return self._worksheet


def test_inventory_grant_appends_new_row_when_recipient_has_no_history():
    ws = _FakeWorksheet(["character_name", "item_id", "count"], [["아군 1", "포션", "1"]])
    spreadsheet = _FakeSpreadsheet(ws)
    inv = Inventory({("아군 1", "포션"): 1}, spreadsheet)

    inv.grant("아군 2", "포션", 3)

    assert ws.appended == [["아군 2", "포션", 3]]
    assert inv.get_count("아군 2", "포션") == 3
