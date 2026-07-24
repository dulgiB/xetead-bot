from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import BattleLogEntryKind
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectConsumeStackForDamage,
    SkillEffectRemoveDebuffs,
)
from battle.objects.skill.models import SkillData
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
    cmd = parse_character_command(CharacterId("아군 1"), "[강타/적군 1]", ctx)
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    assert len(entries) == 1
    assert entries[0].target_name == "적군 1"
    assert entries[0].kind == BattleLogEntryKind.DAMAGE
    assert entries[0].result.startswith("대미지 ")
    assert entries[0].roll_display is not None
    assert entries[0].value == int(entries[0].result.removeprefix("대미지 "))


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
    cmd = parse_character_command(CharacterId("아군 1"), "[회복/아군 2]", ctx)
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    assert len(entries) == 1
    assert entries[0].target_name == "아군 2"
    assert entries[0].kind == BattleLogEntryKind.HEAL
    assert entries[0].result == "회복 10"
    assert entries[0].value == 10


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
    cmd = parse_character_command(CharacterId("아군 1"), "[공격 보조/아군 2]", ctx)
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    assert len(entries) == 1
    assert entries[0].target_name == "아군 2"
    # buff_atk_data는 duration_turn_value=3, duration_count_value=0으로 지속시간이
    # 함께 표시된다 (적층형이 아니므로 스택 수가 아니라 턴/횟수로 표시됨).
    assert "[공격력 증가] 부여 (3턴/0회)" == entries[0].result
    assert entries[0].kind == BattleLogEntryKind.BUFF_ADD
    assert entries[0].buff_id == "공격력 증가"
    assert entries[0].roll_display is None


def test_build_log_entries_records_stacking_buff_add_with_stack_count():
    """max_stack이 있는 적층형 버프는 턴/횟수가 아니라 스택 수로 표시된다."""
    buff = BuffData(
        id="재앙",
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=1,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
        max_stack=5,
    )
    stack_skill = SkillData(
        id="쌓기",
        target_rule="SkillTargetRuleSelf",
        target_count=1,
        cost=0,
        effects=[SkillEffectAddBuff(None, None, None, "재앙", None, buff_stack_cap=2)],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={"재앙": buff}, skill_dict={"쌓기": stack_skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="쌓기"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    before = len(ctx.results)
    cmd = parse_character_command(caster_id, "[쌓기]", ctx)
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    assert len(entries) == 1
    assert entries[0].kind == BattleLogEntryKind.BUFF_ADD
    assert entries[0].buff_id == "재앙"
    assert entries[0].stack_delta == 2
    assert entries[0].result == "[재앙]×2 부여 → 최종 2"


def test_build_log_entries_records_buff_remove_from_stack_consumption():
    """SkillEffectConsumeStackForDamage로 소모된 스택이 BUFF_REMOVE 엔트리로 남아야 한다."""
    stack_buff = BuffData(
        id="재앙",
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=1,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
        max_stack=5,
    )
    consume_skill = SkillData(
        id="전가",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectConsumeStackForDamage(
                ValueSourceType.CONSUMED_BUFF_STACK,
                100,
                ValueType.INTEGER,
                "재앙",
                None,
                buff_stack_cap=2,
            )
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={"재앙": stack_buff}, skill_dict={"전가": consume_skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="전가"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))
    ctx.buff_container.add(
        BuffAddData(given_by=caster_id, applied_to=caster_id, buff_id="재앙", stack_value=3)
    )

    before = len(ctx.results)
    cmd = parse_character_command(caster_id, "[전가/적군 1]", ctx)
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    remove_entries = [e for e in entries if e.kind == BattleLogEntryKind.BUFF_REMOVE]
    assert len(remove_entries) == 1
    assert remove_entries[0].target_name == "아군 1"
    assert remove_entries[0].buff_id == "재앙"
    assert remove_entries[0].stack_delta == 2
    assert remove_entries[0].result == "[재앙]×2 소모 → 최종 1"

    damage_entries = [e for e in entries if e.kind == BattleLogEntryKind.DAMAGE]
    assert len(damage_entries) == 1
    assert damage_entries[0].value == 2


def test_build_log_entries_records_debuff_clear():
    """SkillEffectRemoveDebuffs가 지운 대상은 DEBUFF_CLEAR 엔트리로 남아야 한다."""
    debuff = BuffData(
        id="독",
        buff_class_name="BuffDamageOverTime",
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=5,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
    )
    cleanse_skill = SkillData(
        id="정화",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[SkillEffectRemoveDebuffs(None, None, None, None, None)],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={"독": debuff}, skill_dict={"정화": cleanse_skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    target_id = CharacterId("아군 2")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="정화"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(1))
    ctx.buff_container.add(
        BuffAddData(given_by=caster_id, applied_to=target_id, buff_id="독")
    )

    before = len(ctx.results)
    cmd = parse_character_command(caster_id, "[정화/아군 2]", ctx)
    manager.process_command(cmd)
    new_results = ctx.results[before:]

    entries = [e for r in new_results for e in r.log_entries]
    assert len(entries) == 1
    assert entries[0].kind == BattleLogEntryKind.DEBUFF_CLEAR
    assert entries[0].target_name == "아군 2"
    assert entries[0].result == "모든 디버프 제거"
    assert ctx.buff_container.get_buffs_by(target_id, None) == []


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
