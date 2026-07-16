"""app/bot/battle_reply_text.py의 답글 포맷팅을 실제 커맨드 처리 결과로 검증한다."""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType, ValueSourceType, ValueType
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectConsumeStackForDamage,
    SkillEffectDamage,
    SkillEffectHeal,
    SkillEffectMove,
    SkillEffectRemoveDebuffs,
)
from battle.objects.skill.models import SkillData
from bot.battle_reply_text import format_battle_reply
from helpers import get_test_preset
from spreadsheets.inventory import Inventory


def _ally_action_manager(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION)
    )
    return manager


def _run(ctx: BattlefieldContext, manager: RoundManager, caster_id: CharacterId, text: str) -> str:
    before = len(ctx.results)
    cmd = parse_character_command(caster_id, text, ctx)
    manager.process_command(cmd)
    new_results = ctx.results[before:]
    return format_battle_reply(ctx, caster_id, new_results)


def test_move_command_is_header_only():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0))

    reply = _run(ctx, manager, caster_id, "[이동/3]")

    assert reply == "【이동 ▸ 3열】"


def test_attack_command_shows_damage_and_calculation():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(get_test_preset("아군 1", atk=10), FactionType.ALLY, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))

    reply = _run(ctx, manager, caster_id, "[공격/적군 1]")

    lines = reply.splitlines()
    assert lines[0] == "【공격 ▸ 적군 1】"
    target = ctx.characters[CharacterId("적군 1")]
    assert lines[1] == f"적군 1 | -{100 - target.status.curr_hp} → {target.status.curr_hp}/100"
    assert lines[2].startswith("↳ ")


def test_fixed_damage_skill_omits_calculation_line():
    """FIXED 값은 modifier가 전혀 없으면 계산식(↳) 줄을 생략한다."""
    skill = SkillData(
        id="강타",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[SkillEffectDamage(ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None)],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"강타": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="강타"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))

    reply = _run(ctx, manager, caster_id, "[강타/적군 1]")

    assert reply == "【강타 ▸ 적군 1】\n적군 1 | -20 → 80/100"


def test_self_targeted_skill_header_uses_caster_name():
    buff = BuffData(
        id="집중",
        buff_class_name="BuffAtk",
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=5,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
    )
    skill = SkillData(
        id="집중하기",
        target_rule="SkillTargetRuleSelf",
        target_count=1,
        cost=0,
        effects=[SkillEffectAddBuff(None, None, None, "집중", None)],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={"집중": buff}, skill_dict={"집중하기": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="집중하기"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    reply = _run(ctx, manager, caster_id, "[집중하기]")

    assert reply == "【집중하기 ▸ 아군 1】\n아군 1 | [집중] 부여 (2턴)"


def test_skill_with_damage_and_debuff_clear_combines_lines_in_effect_order():
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
    skill = SkillData(
        id="정화 일격",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None),
            SkillEffectRemoveDebuffs(None, None, None, None, None),
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={"독": debuff}, skill_dict={"정화 일격": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    target_id = CharacterId("적군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="정화 일격"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))
    ctx.buff_container.add(BuffAddData(given_by=caster_id, applied_to=target_id, buff_id="독"))

    reply = _run(ctx, manager, caster_id, "[정화 일격/적군 1]")

    assert reply == (
        "【정화 일격 ▸ 적군 1】\n"
        "적군 1 | -10 → 90/100\n"
        "적군 1 | 모든 디버프 제거"
    )


def test_item_command_header_uses_item_name():
    item = ItemData(
        id="포션",
        target_rule="SkillTargetRuleSelf",
        cost=1,
        attack_range=1,
        effect=SkillEffectHeal(ValueSourceType.FIXED, 15, ValueType.INTEGER, None, None),
    )
    ctx = BattlefieldContext(
        buff_dict={},
        skill_dict={},
        item_dict={"포션": item},
        inventory=Inventory({("아군 1", "포션"): 1}),
    )
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", initial_hp=50), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    reply = _run(ctx, manager, caster_id, "[포션]")

    assert reply == "【포션 ▸ 아군 1】\n아군 1 | +15 → 65/100"


def test_multiple_parts_are_joined_by_blank_line():
    skill = SkillData(
        id="찌르기",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"찌르기": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="찌르기"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))

    reply = _run(ctx, manager, caster_id, "[이동/3 - 찌르기/적군 1]")

    assert reply == (
        "【이동 ▸ 3열】\n"
        "\n"
        "【찌르기 ▸ 적군 1】\n"
        "적군 1 | -5 → 95/100"
    )


def test_column_targeted_skill_header_shows_input_column():
    skill = SkillData(
        id="광역기",
        target_rule="SkillTargetRuleColumn",
        target_count=1,
        cost=0,
        effects=[SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"광역기": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="광역기"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))

    reply = _run(ctx, manager, caster_id, "[광역기/1열]")

    assert reply.startswith("【광역기 ▸ 1열】\n")


def test_move_effect_inside_skill_shows_target_and_position():
    skill = SkillData(
        id="당기기",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[SkillEffectMove(ValueSourceType.TOWARD_HOLDER, 1, ValueType.INTEGER, None, None)],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"당기기": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="당기기"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(3))

    reply = _run(ctx, manager, caster_id, "[당기기/적군 1]")

    # 적군 1은 4열(BattlefieldColumnIndex(3))에서 시전자(1열) 쪽으로 1칸 이동 → 3열.
    assert reply == "【당기기 ▸ 적군 1】\n적군 1 | 3열로 이동"


def test_stack_consume_for_damage_shows_stack_line_before_damage_line():
    """SkillEffectConsumeStackForDamage는 스택 소모 줄이 대미지 줄보다 먼저 나와야 한다
    (실제 계산도 소모 결과를 대미지 값이 참조하는 순서)."""
    stack_buff = BuffData(
        id="저주", buff_class_name="BuffAtk", duration_turn_value=None,
        duration_count_value=None, duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER, value=0, condition_=None, condition_value=None,
        is_debuff=True, description="", max_stack=5,
    )
    skill = SkillData(
        id="저주 방출",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectConsumeStackForDamage(
                ValueSourceType.CONSUMED_BUFF_STACK, 100, ValueType.INTEGER, "저주", None,
                buff_stack_cap=2,
            )
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={"저주": stack_buff}, skill_dict={"저주 방출": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="저주 방출"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0))
    ctx.buff_container.add(BuffAddData(given_by=caster_id, applied_to=caster_id, buff_id="저주", stack_value=3))

    reply = _run(ctx, manager, caster_id, "[저주 방출/적군 1]")

    assert reply == (
        "【저주 방출 ▸ 적군 1】\n"
        "아군 1 | [저주]×2 소모 (잔여 1)\n"
        "적군 1 | -2 → 98/100"
    )
