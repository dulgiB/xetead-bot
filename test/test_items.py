import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectHeal
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import SideType
from bot.sheet_cache import SheetCache
from helpers import get_test_preset
from spreadsheets.inventory import Inventory


# ── 아이템 정의 ────────────────────────────────────────────────────────────────


@pytest.fixture
def item_bomb() -> ItemData:
    """지정 대상에게 고정 30 대미지. 사거리 1(캐릭터 기본 사거리 3보다 짧음)."""
    return ItemData(
        id="폭탄",
        target_rule="SkillTargetRuleNamed",
        cost=1,
        attack_range=1,
        effect=SkillEffectDamage(
            ValueSourceType.FIXED, 30, ValueType.INTEGER, None, None
        ),
    )


@pytest.fixture
def item_potion() -> ItemData:
    """자신을 고정 20 회복하는 아이템 (Self 대상)."""
    return ItemData(
        id="포션",
        target_rule="SkillTargetRuleSelf",
        cost=1,
        attack_range=0,
        effect=SkillEffectHeal(ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None),
    )


def _make_context(item_dict, counts) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={},
        skill_dict={},
        item_dict=item_dict,
        inventory=Inventory(counts),  # spreadsheet=None → 메모리 전용
    )


def _ally_action_manager(ctx) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


# ── 대미지 아이템 ──────────────────────────────────────────────────────────────


@pytest.fixture
def bomb_setup(item_bomb):
    """아군 1(폭탄 2개 보유)과 적군 1이 같은 열(거리 0)에 대치."""
    ctx = _make_context({"폭탄": item_bomb}, {("아군 1", "폭탄"): 2})
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx, manager


def test_item_damage_reduces_hp(bomb_setup):
    """대미지 아이템 사용 후 대상의 HP가 30 감소해야 한다."""
    ctx, manager = bomb_setup
    enemy_id = CharacterId("적군 1")

    cmd = parse_character_command(CharacterId("아군 1"), "[폭탄/적군 1]", ctx)
    manager.process_command(cmd)

    assert ctx.characters[enemy_id].status.curr_hp == 70  # 100 - 30


def test_item_consumes_inventory(bomb_setup):
    """아이템 사용 시 인벤토리 보유 개수가 1 감소해야 한다."""
    ctx, manager = bomb_setup
    assert ctx.inventory.get_count("아군 1", "폭탄") == 2

    cmd = parse_character_command(CharacterId("아군 1"), "[폭탄/적군 1]", ctx)
    manager.process_command(cmd)

    assert ctx.inventory.get_count("아군 1", "폭탄") == 1


def test_item_cost_is_deducted(bomb_setup):
    """아이템(코스트 1) 사용 시 잔여 코스트가 1 감소해야 한다."""
    ctx, manager = bomb_setup
    user_id = CharacterId("아군 1")
    initial_cost = ctx.characters[user_id].status.remaining_cost

    cmd = parse_character_command(user_id, "[폭탄/적군 1]", ctx)
    manager.process_command(cmd)

    assert ctx.characters[user_id].status.remaining_cost == initial_cost - 1


def test_item_uses_own_range_not_character_range(item_bomb):
    """아이템 고유 사거리(1)를 사용해야 한다.

    적군을 거리 2에 배치하면, 캐릭터 사거리(3)로는 닿지만 아이템 사거리(1)로는 닿지 않아
    error가 발생해야 한다.
    """
    ctx = _make_context({"폭탄": item_bomb}, {("아군 1", "폭탄"): 1})
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(2)
    )

    cmd = parse_character_command(CharacterId("아군 1"), "[폭탄/적군 1]", ctx)
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)


def test_item_not_in_inventory_raises(item_bomb):
    """보유 개수가 0인 아이템은 사용할 수 없어야 한다."""
    ctx = _make_context({"폭탄": item_bomb}, {("아군 1", "폭탄"): 0})
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    cmd = parse_character_command(CharacterId("아군 1"), "[폭탄/적군 1]", ctx)
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)


def test_unregistered_item_raises(item_bomb):
    """'아이템' 시트에 없는 아이템은 사용할 수 없어야 한다."""
    ctx = _make_context({"폭탄": item_bomb}, {("아군 1", "존재하지 않는 아이템"): 5})
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    with pytest.raises(CommandValidationError):
        cmd = parse_character_command(
            CharacterId("아군 1"), "[존재하지 않는 아이템]", ctx
        )
        manager.process_command(cmd)


# ── 자기 대상 아이템 ───────────────────────────────────────────────────────────


def test_self_item_heals_user(item_potion):
    """Self 대상 아이템(포션)은 시전자 자신을 회복해야 한다."""
    ctx = _make_context({"포션": item_potion}, {("아군 1", "포션"): 1})
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", initial_hp=50),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )

    # 대상 미지정 → 파서가 자신에게 사용한 것으로 간주
    cmd = parse_character_command(CharacterId("아군 1"), "[포션]", ctx)
    manager.process_command(cmd)

    assert ctx.characters[CharacterId("아군 1")].status.curr_hp == 70  # 50 + 20


# ── 대련 차단 ──────────────────────────────────────────────────────────────────


def test_practice_battle_blocks_item():
    """대련 전장에서는 아이템 커맨드를 사용할 수 없어야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    ctx.add_character(
        get_test_preset("전사"), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )

    with pytest.raises(CommandValidationError):
        cmd = parse_character_command(CharacterId("전사"), "[포션]", ctx)
        manager.process_command(cmd)


def test_practice_battle_blocks_item_with_specific_message(item_potion):
    """PracticeBattlefieldContext에 item_dict를 넘기지 않으면(예: 위 테스트처럼
    빈 dict) 파서가 "포션"을 스킬도 아이템도 아닌 것으로 오인해 부정확한
    에러("등록된 스킬도 아이템도 아닙니다")를 낸다. item_dict를 제대로
    넘기면 이름은 정상 인식되고, 실제 사용 차단은 allow_item_usage 검증에서
    "이 전투에서는 아이템을 사용할 수 없습니다."라는 정확한 메시지로
    일어나야 한다."""
    ctx = PracticeBattlefieldContext(
        buff_dict={}, skill_dict={}, item_dict={"포션": item_potion}
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    ctx.add_character(
        get_test_preset("전사"), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )

    cmd = parse_character_command(CharacterId("전사"), "[포션]", ctx)
    with pytest.raises(CommandValidationError, match="이 전투에서는 아이템을 사용할 수 없습니다"):
        manager.process_command(cmd)


# ── 인벤토리 양도 ──────────────────────────────────────────────────────────────


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

    def get_values(self, value_render_option=None, pad_values=True):
        return [self._header] + [list(row) for row in self._rows]

    def update_cell(self, row_idx, col_idx, value):
        self._rows[row_idx - 2][col_idx - 1] = value

    def append_row(self, row, value_input_option=None):
        self.appended.append(row)
        self._rows.append(row)


class _FakeSpreadsheet:
    def __init__(self, worksheet):
        self._worksheet = worksheet
        self.id = "fake-inventory-spreadsheet-id"
        self.client = None
        self.fetch_sheet_metadata_call_count = 0

    def worksheet(self, _name):
        return self._worksheet

    def fetch_sheet_metadata(self):
        self.fetch_sheet_metadata_call_count += 1
        return {"sheets": [{"properties": {"title": "인벤토리"}}]}


def test_inventory_grant_updates_existing_row():
    inv = Inventory({("아군 1", "포션"): 1})
    inv.grant("아군 1", "포션", 2)
    assert inv.get_count("아군 1", "포션") == 3


def test_inventory_grant_creates_new_entry_when_absent():
    inv = Inventory({})
    inv.grant("아군 2", "포션", 1)
    assert inv.get_count("아군 2", "포션") == 1


def test_inventory_grant_appends_new_row_when_recipient_has_no_history():
    ws = _FakeWorksheet(["character_name", "item_id", "count"], [["아군 1", "포션", "1"]])
    spreadsheet = _FakeSpreadsheet(ws)
    inv = Inventory({("아군 1", "포션"): 1}, spreadsheet)

    inv.grant("아군 2", "포션", 3)

    assert ws.appended == [["아군 2", "포션", 3]]
    assert inv.get_count("아군 2", "포션") == 3


def test_inventory_write_back_uses_cache_when_set():
    """`cache`가 설정돼 있으면(handle_character_command 등이 매 멘션마다
    갱신) 시트 메타데이터 조회를 캐시가 공유해야 하고, 쓰기 직후 캐시가
    무효화돼 바로 다음 읽기(같은 멘션 안의 양도처럼 consume→grant 연속 호출)가
    낡은 값을 보지 않아야 한다."""
    ws = _FakeWorksheet(
        ["character_name", "item_id", "count"],
        [["아군 1", "포션", "3"], ["아군 2", "포션", "0"]],
    )
    spreadsheet = _FakeSpreadsheet(ws)
    cache = SheetCache(
        spreadsheet,
        worksheet_factory=lambda properties: ws,
    )
    inv = Inventory({("아군 1", "포션"): 3, ("아군 2", "포션"): 0}, spreadsheet)
    inv.cache = cache

    # 양도: 소비 후 지급 — 두 호출 모두 캐시를 거치지만 메타데이터는 1회만.
    inv.consume("아군 1", "포션", 1)
    inv.grant("아군 2", "포션", 1)

    assert spreadsheet.fetch_sheet_metadata_call_count == 1
    assert ws._rows[0] == ["아군 1", "포션", 2]
    assert ws._rows[1] == ["아군 2", "포션", 1]

    # consume이 쓴 뒤 캐시가 무효화되지 않았다면 grant가 낡은(변경 전) 값을
    # 읽어 "아군 2" 행을 못 찾거나 잘못된 행을 갱신했을 것이다 — 실제로는
    # 정확한 행(두 번째)이 갱신됐으므로 무효화가 정상 동작한 것이다.
