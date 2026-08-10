"""app/bot/battle_reply_text.py의 답글 포맷팅을 실제 커맨드 처리 결과로 검증한다."""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
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
from bot.battle_reply_text import (
    format_battle_reply,
    format_eliminated_characters,
    format_final_hp_roster,
    format_round_end_log_entries,
)
from helpers import get_test_preset
from spreadsheets.inventory import Inventory


def _ally_action_manager(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


def _run(
    ctx: BattlefieldContext, manager: RoundManager, caster_id: CharacterId, text: str
) -> tuple[str, str]:
    before = len(ctx.results)
    cmd = parse_character_command(caster_id, text, ctx)
    manager.process_command(cmd)
    new_results = ctx.results[before:]
    return format_battle_reply(ctx, caster_id, new_results)


def test_move_command_is_header_only():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    reply, calc = _run(ctx, manager, caster_id, "[이동/3]")

    assert reply == "【이동 ▸ 3열】"
    assert calc == ""


def test_attack_command_separates_damage_and_calculation():
    """대미지 줄(본문)과 계산식은 별도의 텍스트로 반환되어야 한다 — 계산식은
    호출측이 접힌(CW) 게시물로 따로 보내기 위함이다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", atk=10), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    reply, calc = _run(ctx, manager, caster_id, "[공격/적군 1]")

    lines = reply.splitlines()
    assert lines[0] == "【공격 ▸ 적군 1】"
    target = ctx.characters[CharacterId("적군 1")]
    assert (
        lines[1]
        == f"▹ 적군 1 | -{100 - target.status.curr_hp} → {target.status.curr_hp}/100"
    )
    assert len(lines) == 2
    assert "↳" not in reply

    calc_lines = calc.splitlines()
    assert calc_lines[0] == "【공격 ▸ 적군 1】"
    assert calc_lines[1].startswith("▹ 적군 1 | ")
    assert f"→ -{100 - target.status.curr_hp}" in calc_lines[1]


def test_fixed_damage_skill_omits_calculation_line():
    """FIXED 값은 modifier가 전혀 없으면 계산식(↳) 줄을 생략한다."""
    skill = SkillData(
        id="강타",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"강타": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="강타"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    reply, calc = _run(ctx, manager, caster_id, "[강타/적군 1]")

    assert reply == "【강타 ▸ 적군 1】\n▹ 적군 1 | -20 → 80/100"
    assert calc == ""


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
        get_test_preset("아군 1", skill_1_id="집중하기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )

    reply, _calc = _run(ctx, manager, caster_id, "[집중하기]")

    assert reply == "【집중하기 ▸ 아군 1】\n▹ 아군 1 | [집중] 부여 (2턴)"


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
        get_test_preset("아군 1", skill_1_id="정화 일격"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.buff_container.add(
        BuffAddData(given_by=caster_id, applied_to=target_id, buff_id="독")
    )

    reply, _calc = _run(ctx, manager, caster_id, "[정화 일격/적군 1]")

    assert reply == (
        "【정화 일격 ▸ 적군 1】\n▹ 적군 1 | -10 → 90/100\n▹ 적군 1 | 모든 디버프 제거"
    )


def test_item_command_header_uses_item_name():
    item = ItemData(
        id="포션",
        target_rule="SkillTargetRuleSelf",
        cost=1,
        attack_range=1,
        effect=SkillEffectHeal(
            ValueSourceType.FIXED, 15, ValueType.INTEGER, None, None
        ),
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
        get_test_preset("아군 1", initial_hp=50),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )

    reply, _calc = _run(ctx, manager, caster_id, "[포션]")

    assert reply == "【포션 ▸ 아군 1】\n▹ 아군 1 | +15 → 65/100"


def test_multiple_parts_are_joined_by_blank_line():
    skill = SkillData(
        id="찌르기",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"찌르기": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="찌르기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    reply, _calc = _run(ctx, manager, caster_id, "[이동/3 - 찌르기/적군 1]")

    assert reply == ("【이동 ▸ 3열】\n\n【찌르기 ▸ 적군 1】\n▹ 적군 1 | -5 → 95/100")


def test_column_targeted_skill_header_shows_input_column():
    skill = SkillData(
        id="광역기",
        target_rule="SkillTargetRuleColumn",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"광역기": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="광역기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    reply, _calc = _run(ctx, manager, caster_id, "[광역기/1열]")

    assert reply.startswith("【광역기 ▸ 1열】\n")


def test_move_effect_inside_skill_shows_target_and_position():
    skill = SkillData(
        id="당기기",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectMove(
                ValueSourceType.TOWARD_HOLDER, 1, ValueType.INTEGER, None, None
            )
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"당기기": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="당기기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )

    reply, _calc = _run(ctx, manager, caster_id, "[당기기/적군 1]")

    # 적군 1은 4열(BattlefieldColumnIndex(3))에서 시전자(1열) 쪽으로 1칸 이동 → 3열.
    assert reply == "【당기기 ▸ 적군 1】\n▹ 적군 1 | 3열로 이동"


def test_stack_consume_for_damage_shows_stack_line_before_damage_line():
    """SkillEffectConsumeStackForDamage는 스택 소모 줄이 대미지 줄보다 먼저 나와야 한다
    (실제 계산도 소모 결과를 대미지 값이 참조하는 순서)."""
    stack_buff = BuffData(
        id="저주",
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
        max_stack=5,
    )
    skill = SkillData(
        id="저주 방출",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectConsumeStackForDamage(
                ValueSourceType.CONSUMED_BUFF_STACK,
                100,
                ValueType.INTEGER,
                "저주",
                None,
                buff_stack_cap=2,
            )
        ],
        description="",
    )
    ctx = BattlefieldContext(
        buff_dict={"저주": stack_buff}, skill_dict={"저주 방출": skill}
    )
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="저주 방출"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.buff_container.add(
        BuffAddData(
            given_by=caster_id, applied_to=caster_id, buff_id="저주", stack_value=3
        )
    )

    reply, calc = _run(ctx, manager, caster_id, "[저주 방출/적군 1]")

    assert reply == (
        "【저주 방출 ▸ 적군 1】\n"
        "▹ 아군 1 | [저주]×2 소모 → 최종 1\n"
        "▹ 적군 1 | -2 → 98/100"
    )
    assert calc == "【저주 방출 ▸ 적군 1】\n▹ 적군 1 | 2[저주] × 1 → -2"


def test_multi_effect_skill_combines_roll_and_stack_consume_damage():
    """공격 굴림 기반 대미지 + 버프 스택 소모 대미지가 같은 대상에게 함께 들어가는
    스킬(예: 반송형 스킬)은 한 줄로 합쳐서 보여줘야 하고, 스택 소모 항목은
    버프 이름으로 라벨링되어야 한다."""
    stack_buff = BuffData(
        id="저주",
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
        max_stack=10,
    )
    skill = SkillData(
        id="이중 타격",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(
                ValueSourceType.STAT_ATK, 150, ValueType.INTEGER, None, None
            ),
            SkillEffectConsumeStackForDamage(
                ValueSourceType.CONSUMED_BUFF_STACK,
                300,
                ValueType.INTEGER,
                "저주",
                None,
                buff_stack_cap=5,
            ),
        ],
        description="",
    )
    ctx = BattlefieldContext(
        buff_dict={"저주": stack_buff}, skill_dict={"이중 타격": skill}
    )
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="이중 타격", atk=6),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.buff_container.add(
        BuffAddData(
            given_by=caster_id, applied_to=caster_id, buff_id="저주", stack_value=5
        )
    )

    reply, calc = _run(ctx, manager, caster_id, "[이중 타격/적군 1]")

    # STAT_ATK(다이스 없음) 6 × 1.5[계수] = 9, 스택 소모 5 × 3[계수] = 15 → 합계 24
    assert reply == (
        "【이중 타격 ▸ 적군 1】\n"
        "▹ 아군 1 | [저주]×5 소모 → 최종 0\n"
        "▹ 적군 1 | -24 → 76/100"
    )
    assert (
        calc == "【이중 타격 ▸ 적군 1】\n▹ 적군 1 | 6 × 1.5[계수] + 5[저주] × 3 → -24"
    )


def test_multiple_damage_effects_on_same_target_are_merged_into_one_hit():
    """같은 대상이 한 스킬 안의 여러 effect로 대미지를 받으면, 실제로는 한 번의
    타격이므로 두 줄로 나뉘어 순차 HP를 보여주는 대신 합산된 값 한 줄로
    보여줘야 한다. 계산식은 각 구성 요소를 "+"로 이어붙인다."""
    skill = SkillData(
        id="연타",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None),
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None),
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"연타": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="연타"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    reply, calc = _run(ctx, manager, caster_id, "[연타/적군 1]")

    assert reply == ("【연타 ▸ 적군 1】\n▹ 적군 1 | -15 → 85/100")
    assert calc == "【연타 ▸ 적군 1】\n▹ 적군 1 | 10 + 5 → -15"


# ── 라운드 종료 처리(DoT/HoT) 답글 포맷팅 ────────────────────────────────────────


def _dot_buff_data(*, buff_id: str = "DoT", value: int = 10) -> BuffData:
    return BuffData.from_dict(
        {
            "id": buff_id,
            "buff_name": "BuffDamageOverTime",
            "duration_turn_value": 2,
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value": value,
            "value_type": "정수",
            "condition": "",
            "condition_value": "",
            "description": "",
            "is_debuff": True,
        }
    )


def _hot_buff_data(*, buff_id: str = "HoT", value: int = 10) -> BuffData:
    return BuffData.from_dict(
        {
            "id": buff_id,
            "buff_name": "BuffHealOverTime",
            "duration_turn_value": 2,
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value": value,
            "value_type": "정수",
            "condition": "",
            "condition_value": "",
            "description": "",
            "is_debuff": False,
        }
    )


def test_round_end_dot_produces_round_end_processing_block():
    """라운드 종료 시 발동한 DoT는 "【라운드 종료 처리 ▸ 대상】" 블록으로
    나와야 한다."""
    ctx = BattlefieldContext(buff_dict={"DoT": _dot_buff_data(value=10)}, skill_dict={})
    manager = RoundManager(ctx)
    enemy_id = CharacterId("적군 1")
    ctx.add_character(
        get_test_preset("적군 1", max_hp=100),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.buff_container.add(
        BuffAddData(given_by=enemy_id, applied_to=enemy_id, buff_id="DoT")
    )

    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
    body, calc = format_round_end_log_entries(
        ctx, manager.get_last_round_end_log_entries()
    )

    assert body == "【라운드 종료 처리 ▸ 적군 1】\n▹ 적군 1 | -10 → 90/100"
    assert calc == ""


def test_round_end_hot_uses_plus_sign():
    """라운드 종료 시 발동한 HoT는 "-"가 아니라 "+" 부호로 표시돼야 한다."""
    ctx = BattlefieldContext(buff_dict={"HoT": _hot_buff_data(value=7)}, skill_dict={})
    manager = RoundManager(ctx)
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", initial_hp=50, max_hp=100),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.buff_container.add(
        BuffAddData(given_by=ally_id, applied_to=ally_id, buff_id="HoT")
    )

    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
    body, calc = format_round_end_log_entries(
        ctx, manager.get_last_round_end_log_entries()
    )

    assert body == "【라운드 종료 처리 ▸ 아군 1】\n▹ 아군 1 | +7 → 57/100"
    assert calc == ""


def test_round_end_groups_multiple_targets_into_separate_blocks():
    """서로 다른 대상에게 발동한 라운드 종료 효과는 대상별로 블록이
    나뉘어야 한다."""
    ctx = BattlefieldContext(
        buff_dict={"DoT": _dot_buff_data(value=10), "HoT": _hot_buff_data(value=7)},
        skill_dict={},
    )
    manager = RoundManager(ctx)
    enemy_id = CharacterId("적군 1")
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("적군 1", max_hp=100),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 1", initial_hp=50, max_hp=100),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.buff_container.add(
        BuffAddData(given_by=enemy_id, applied_to=enemy_id, buff_id="DoT")
    )
    ctx.buff_container.add(
        BuffAddData(given_by=ally_id, applied_to=ally_id, buff_id="HoT")
    )

    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
    body, calc = format_round_end_log_entries(
        ctx, manager.get_last_round_end_log_entries()
    )

    assert body == (
        "【라운드 종료 처리 ▸ 적군 1】\n"
        "▹ 적군 1 | -10 → 90/100\n\n"
        "【라운드 종료 처리 ▸ 아군 1】\n"
        "▹ 아군 1 | +7 → 57/100"
    )
    assert calc == ""


def test_round_end_returns_empty_string_when_nothing_fires():
    """발동한 ON_ROUND_END 효과가 없으면 빈 문자열을 반환해야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = RoundManager(ctx)
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
    body, calc = format_round_end_log_entries(
        ctx, manager.get_last_round_end_log_entries()
    )

    assert body == ""
    assert calc == ""


def test_round_end_stack_proportional_dot_shows_calculation_line():
    """다른 버프의 스택 수에 비례하는 라운드 종료 DoT(예:
    BuffDamageOverTimePerReferencedBuffStack)는 재앙/균열 계열과 동일하게
    "{스택}[{버프id}] × {배율}" 형태의 계산식이 함께 표시돼야 한다."""
    mark = BuffData.from_dict(
        {
            "id": "Mark",
            "buff_name": "BuffStackingMark",
            "duration_turn_value": 2,
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value": "",
            "value_type": "",
            "condition": "",
            "condition_value": "",
            "description": "",
            "is_debuff": True,
            "max_stack": 3,
        }
    )
    mark_drain = BuffData.from_dict(
        {
            "id": "MarkDrain",
            "buff_name": "BuffDamageOverTimePerReferencedBuffStack",
            "duration_turn_value": 2,
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value": 5,
            "value_type": "정수",
            "condition": "",
            "condition_value": "",
            "description": "",
            "is_debuff": True,
            "reference_buff_id": "Mark",
        }
    )
    ctx = BattlefieldContext(
        buff_dict={"Mark": mark, "MarkDrain": mark_drain}, skill_dict={}
    )
    manager = RoundManager(ctx)
    enemy_id = CharacterId("적군 1")
    ctx.add_character(
        get_test_preset("적군 1", max_hp=100),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.buff_container.add(
        BuffAddData(
            given_by=enemy_id, applied_to=enemy_id, buff_id="Mark", stack_value=3
        )
    )
    ctx.buff_container.add(
        BuffAddData(given_by=enemy_id, applied_to=enemy_id, buff_id="MarkDrain")
    )

    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
    body, calc = format_round_end_log_entries(
        ctx, manager.get_last_round_end_log_entries()
    )

    assert body == "【라운드 종료 처리 ▸ 적군 1】\n▹ 적군 1 | -15 → 85/100"
    assert calc == "【라운드 종료 처리 ▸ 적군 1】\n▹ 적군 1 | 3[Mark] × 5 → -15"


# ── 적 스킬 선언 예고(블라인드/공개) ────────────────────────────────────────


def _declare_enemy_skill(ctx: BattlefieldContext, skill_id: str, cmd_str: str) -> list:
    """RoundManager 기본 페이즈(ENEMY_PRE_ACTION)에서 적군 캐릭터로 스킬을
    선언하고 그 커맨드가 만든 CommandPartProcessResult 목록을 반환한다."""
    manager = RoundManager(ctx)
    caster_id = CharacterId("적군 1")
    before = len(ctx.results)
    cmd = parse_character_command(caster_id, cmd_str, ctx)
    manager.process_command(cmd)
    return caster_id, ctx.results[before:]


def test_enemy_skill_preview_shows_description_when_revealed():
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="대상에게 고정 피해를 준다.",
        revealed=True,
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})
    ctx.add_character(
        get_test_preset("적군 1", skill_1_id="스킬_1"),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    caster_id, new_results = _declare_enemy_skill(ctx, "스킬_1", "[스킬_1/아군 1]")
    reply, _calc = format_battle_reply(
        ctx, caster_id, new_results, show_skill_preview=True
    )

    assert reply == "【스킬_1 ▸ 아군 1】\n　↳ 대상에게 고정 피해를 준다."


def test_enemy_skill_preview_blinds_description_when_not_revealed():
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="대상에게 고정 피해를 준다.",
        revealed=False,
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})
    ctx.add_character(
        get_test_preset("적군 1", skill_1_id="스킬_1"),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    caster_id, new_results = _declare_enemy_skill(ctx, "스킬_1", "[스킬_1/아군 1]")
    reply, _calc = format_battle_reply(
        ctx, caster_id, new_results, show_skill_preview=True
    )

    assert reply == "【스킬_1 ▸ 아군 1】\n　↳ [효과 미확인]"


def test_skill_preview_omitted_when_show_skill_preview_is_false():
    """show_skill_preview 기본값(False)은 기존 동작대로 예고 줄을 붙이지 않는다."""
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="대상에게 고정 피해를 준다.",
        revealed=False,
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})
    ctx.add_character(
        get_test_preset("적군 1", skill_1_id="스킬_1"),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    caster_id, new_results = _declare_enemy_skill(ctx, "스킬_1", "[스킬_1/아군 1]")
    reply, _calc = format_battle_reply(ctx, caster_id, new_results)

    assert reply == "【스킬_1 ▸ 아군 1】"


def test_mark_skill_revealed_updates_skill_dict_in_place():
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="",
        revealed=False,
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})

    ctx.mark_skill_revealed("스킬_1")

    assert ctx.get_skill_data_by_id("스킬_1").revealed is True


def test_mark_skill_revealed_is_noop_when_already_revealed():
    """이미 공개된 스킬은 다시 마킹해도 SkillData 인스턴스를 새로 만들지 않는다."""
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="",
        revealed=True,
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": skill})

    ctx.mark_skill_revealed("스킬_1")

    assert ctx.get_skill_data_by_id("스킬_1") is skill


def test_format_eliminated_characters_lists_names_without_trailing_label():
    """각 줄은 다른 헤더들과 마찬가지로 이름만 보여줘야 한다 — "| 탈락"처럼
    헤더에서 이미 드러난 정보를 항목마다 반복하면 안 된다."""
    text = format_eliminated_characters([CharacterId("적군 1"), CharacterId("적군 2")])

    assert text == "【탈락】\n▹ 적군 1\n▹ 적군 2"


def test_format_eliminated_characters_empty_when_no_one_eliminated():
    assert format_eliminated_characters([]) == ""


def test_format_final_hp_roster_nests_companion_under_owner():
    """동료(소환수)는 항상 맨 아래에 나열되는 대신 owner 캐릭터 줄 바로
    아래에 "　↳ {이름} | ..."로 중첩되어야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("아군 1", max_hp=100),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("동료", max_hp=26), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군 2", max_hp=50),
        FactionType.ALLY,
        BattlefieldColumnIndex(1),
    )
    ctx.companion_owners[CharacterId("동료")] = CharacterId("아군 1")

    roster = format_final_hp_roster(ctx)

    assert roster == ("▹ 아군 1 | 100/100\n　↳ 동료 | 26/26\n▹ 아군 2 | 50/50")


def test_format_final_hp_roster_shows_orphaned_companion_at_top_level():
    """owner가 전투 중 이미 전장에서 제거되어 없다면, 그 동료는 중첩 없이
    최상위 "▹" 줄로 보여야 한다(누락되면 안 된다)."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset("동료", max_hp=26), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.companion_owners[CharacterId("동료")] = CharacterId("사라진 오너")

    roster = format_final_hp_roster(ctx)

    assert roster == "▹ 동료 | 26/26"
