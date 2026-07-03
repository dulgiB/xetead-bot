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

    cmd = parse_character_command(CharacterId("아군 1"), "[아이템/폭탄/적군 1]")
    manager.process_command(cmd)

    assert ctx.characters[enemy_id].status.curr_hp == 70  # 100 - 30


def test_item_consumes_inventory(bomb_setup):
    """아이템 사용 시 인벤토리 보유 개수가 1 감소해야 한다."""
    ctx, manager = bomb_setup
    assert ctx.inventory.get_count("아군 1", "폭탄") == 2

    cmd = parse_character_command(CharacterId("아군 1"), "[아이템/폭탄/적군 1]")
    manager.process_command(cmd)

    assert ctx.inventory.get_count("아군 1", "폭탄") == 1


def test_item_cost_is_deducted(bomb_setup):
    """아이템(코스트 1) 사용 시 잔여 코스트가 1 감소해야 한다."""
    ctx, manager = bomb_setup
    user_id = CharacterId("아군 1")
    initial_cost = ctx.characters[user_id].status.remaining_cost

    cmd = parse_character_command(user_id, "[아이템/폭탄/적군 1]")
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

    cmd = parse_character_command(CharacterId("아군 1"), "[아이템/폭탄/적군 1]")
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

    cmd = parse_character_command(CharacterId("아군 1"), "[아이템/폭탄/적군 1]")
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)


def test_unregistered_item_raises(item_bomb):
    """'아이템' 시트에 없는 아이템은 사용할 수 없어야 한다."""
    ctx = _make_context({"폭탄": item_bomb}, {("아군 1", "존재하지 않는 아이템"): 5})
    manager = _ally_action_manager(ctx)
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    cmd = parse_character_command(
        CharacterId("아군 1"), "[아이템/존재하지 않는 아이템]"
    )
    with pytest.raises(CommandValidationError):
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
    cmd = parse_character_command(CharacterId("아군 1"), "[아이템/포션]")
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

    cmd = parse_character_command(CharacterId("전사"), "[아이템/포션]")
    with pytest.raises(CommandValidationError):
        manager.process_command(cmd)
