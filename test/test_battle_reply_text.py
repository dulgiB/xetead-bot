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


def test_move_command_shows_destination_column():
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    reply, calc = _run(ctx, manager, caster_id, "[이동/3]")

    assert reply == "▹ 아군 1 | 3열로 이동"
    assert calc == ""


def test_split_move_reply_shows_only_final_destination_once():
    """한 커맨드 안에서 이동을 여러 번 나눠 선언해도(이동/2열-이동/3열-이동/4열)
    경유지 하나하나가 아니라 최종 목적지 한 줄로만 보여야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", max_cost=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )

    reply, calc = _run(ctx, manager, caster_id, "[이동/2열-이동/3열-이동/4열]")

    assert reply == "▹ 아군 1 | 4열로 이동"
    assert calc == ""


def test_non_consecutive_moves_each_shown_with_own_destination():
    """이동 사이에 다른 행동이 끼면(이동/2열-공격/적군 1-이동/3열) 연속이
    아니므로 병합되지 않고 각각 남아야 하며, 첫 이동은 모든 행동이 끝난
    뒤의 최종 위치가 아니라 그 시점에 실제로 이동한 목적지를 보여줘야
    한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", attack_range=3, max_cost=4),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    reply, _calc = _run(ctx, manager, caster_id, "[이동/2열-공격/적군 1-이동/3열]")

    lines = reply.splitlines()
    assert lines[0] == "▹ 아군 1 | 2열로 이동"
    assert lines[-1] == "▹ 아군 1 | 3열로 이동"


def test_taunted_attacker_header_shows_original_and_redirected_target():
    """도발(BuffTaunt) 상태인 공격자가 다른 대상을 공격하면 실제로는
    도발자에게 리다이렉트된다 — 헤더에 "원래 대상 ▸ 실제 대상"을 함께
    보여줘야 답글만 보고도 왜 이 대상이 맞았는지 알 수 있다."""
    taunt = BuffData(
        id="도발",
        buff_class_name="BuffTaunt",
        duration_turn_value=1,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=None,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
    )
    ctx = BattlefieldContext(buff_dict={"도발": taunt}, skill_dict={})
    taunter_id = CharacterId("아군 1")
    original_target_id = CharacterId("아군 2")
    attacker_id = CharacterId("적군 1")
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.buff_container.add(
        BuffAddData(given_by=taunter_id, applied_to=attacker_id, buff_id="도발")
    )

    manager = RoundManager(ctx)  # 기본 페이즈: ENEMY_PRE_ACTION
    cmd = parse_character_command(attacker_id, f"[공격/{original_target_id.name}]", ctx)
    manager.process_command(cmd)  # PRE 선언 — 대미지는 아직 정산되지 않는다
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    # POST 정산 결과만 확인한다 — 도발 리다이렉트는 실제 대미지가 적용되는
    # 시점(POST)에 계산되므로, PRE 선언 답글은 (아직 리다이렉트를 몰라)
    # 원래 대상만 보여주는 것이 맞다.
    before = len(ctx.results)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
    new_results = ctx.results[before:]

    reply, calc = format_battle_reply(ctx, attacker_id, new_results)

    assert calc.startswith(
        f"**【공격 ▸ {original_target_id.name} ▸ {taunter_id.name}】**"
    )
    assert f"▹ {taunter_id.name} |" in reply
    assert original_target_id.name not in reply


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
    target = ctx.characters[CharacterId("적군 1")]
    assert (
        lines[0]
        == f"▹ 적군 1 | -{100 - target.status.curr_hp} → {target.status.curr_hp}/100"
    )
    assert len(lines) == 1
    assert "↳" not in reply

    calc_lines = calc.splitlines()
    assert calc_lines[0] == "**【공격 ▸ 적군 1】**"
    assert calc_lines[1].startswith("▹ 적군 1 | ")
    assert f"→ -{100 - target.status.curr_hp}" in calc_lines[1]


def test_repeated_attacks_on_same_target_merge_into_one_summary_line():
    """공격을 여러 차례 해도(예: [공격/적군 1 - 공격/적군 1 - 공격/적군 1])
    요약(본문)에는 같은 대상의 체력 변화가 합산된 한 줄로만 보여야 한다
    — 계산식에는 각 타격의 굴림이 그대로 3번 남는다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", atk=5, max_cost=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1", max_hp=500),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )

    reply, calc = _run(
        ctx, manager, caster_id, "[공격/적군 1 - 공격/적군 1 - 공격/적군 1]"
    )

    target = ctx.characters[CharacterId("적군 1")]
    total_damage = 500 - target.status.curr_hp
    assert reply.splitlines() == [
        f"▹ 적군 1 | -{total_damage} → {target.status.curr_hp}/500"
    ]

    calc_headers = [
        line for line in calc.splitlines() if line == "**【공격 ▸ 적군 1】**"
    ]
    assert len(calc_headers) == 3


def test_repeated_stackable_buff_add_on_same_target_merges_into_one_summary_line():
    """스킬을 여러 차례 써서(예: [스킬/적군 1 - 스킬/적군 1 - 스킬/적군 1]) 같은
    적층형 버프를 같은 대상에게 매번 1스택씩 부여하면, 요약(본문)에는
    "[버프]×1 부여 → 최종 1/2/3"처럼 부여 횟수만큼 줄이 늘어나지 않고
    "[버프]×3 부여 → 최종 3" 한 줄로 합쳐져야 한다."""
    ignite = BuffData(
        id="그을음",
        buff_class_name="BuffReceivedDamage",
        duration_turn_value=1,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=5,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
        max_stack=10,
    )
    skill = SkillData(
        id="거화",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None),
            SkillEffectAddBuff(None, None, None, "그을음", None),
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={"그을음": ignite}, skill_dict={"거화": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="거화", max_cost=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1", max_hp=500),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )

    reply, _calc = _run(
        ctx, manager, caster_id, "[거화/적군 1 - 거화/적군 1 - 거화/적군 1]"
    )

    assert "▹ 적군 1 | [그을음]×3 부여 → 최종 3" in reply.splitlines()
    assert reply.count("그을음") == 1


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

    assert reply == "▹ 적군 1 | -20 → 80/100"
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

    assert reply == "▹ 아군 1 | [집중] 부여 (2턴)"


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

    assert reply == "▹ 적군 1 | -10 → 90/100\n▹ 적군 1 | 모든 디버프 제거"


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

    assert reply == "▹ 아군 1 | +15 → 65/100"


def test_multiple_parts_results_are_joined_without_headers():
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

    assert reply == ("▹ 아군 1 | 3열로 이동\n▹ 적군 1 | -5 → 95/100")


def test_column_targeted_skill_calc_header_shows_input_column():
    """계산식(접힌 본문) 블록의 헤더는 실제 대상이 아니라 입력된 열
    번호를 그대로 보여줘야 한다 — 본문(요약)에는 더 이상 헤더가 없으므로
    calc 쪽에서만 검증한다."""
    skill = SkillData(
        id="광역기",
        target_rule="SkillTargetRuleColumn",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(
                ValueSourceType.STAT_ATK, 150, ValueType.INTEGER, None, None
            )
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"광역기": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="광역기", atk=6),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    reply, calc = _run(ctx, manager, caster_id, "[광역기/1열]")

    assert reply == "▹ 적군 1 | -9 → 91/100"
    assert calc == "**【광역기 ▸ 1열】**\n▹ 적군 1 | 6 × 1.5[계수] → -9"


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
    assert reply == "▹ 적군 1 | 3열로 이동"


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

    assert reply == ("▹ 아군 1 | [저주]×2 소모 → 최종 1\n▹ 적군 1 | -2 → 98/100")
    assert calc == "**【저주 방출 ▸ 적군 1】**\n▹ 적군 1 | 2[저주] × 1 → -2"


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
    assert reply == ("▹ 아군 1 | [저주]×5 소모 → 최종 0\n▹ 적군 1 | -24 → 76/100")
    assert (
        calc
        == "**【이중 타격 ▸ 적군 1】**\n▹ 적군 1 | 6 × 1.5[계수] + 5[저주] × 3 → -24"
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

    assert reply == "▹ 적군 1 | -15 → 85/100"
    assert calc == "**【연타 ▸ 적군 1】**\n▹ 적군 1 | 10 + 5 → -15"


# ── 라운드 종료 처리(DoT/HoT) 답글 포맷팅 ────────────────────────────────────────


def _dot_buff_data(*, buff_id: str = "DoT", value: int = 10) -> BuffData:
    return BuffData.from_dict(
        {
            "id": buff_id,
            "buff_name": "BuffDamageOverTime",
            "duration_turn_value": 2,
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value_0": value,
            "value_type_0": "정수",
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
            "value_0": value,
            "value_type_0": "정수",
            "condition": "",
            "condition_value": "",
            "description": "",
            "is_debuff": False,
        }
    )


def test_round_end_dot_produces_round_end_processing_block():
    """라운드 종료 시 발동한 DoT는 "**【라운드 종료 처리 ▸ 대상】**" 블록으로
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

    assert (
        body
        == "**【라운드 종료 처리 ▸ 적군 1】**\n▹ 적군 1 | -10 → 90/100 [DoT: 적군 1]"
    )
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

    assert body == "**【라운드 종료 처리 ▸ 아군 1】**\n▹ 아군 1 | +7 → 57/100"
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
        "**【라운드 종료 처리 ▸ 적군 1】**\n"
        "▹ 적군 1 | -10 → 90/100 [DoT: 적군 1]\n\n"
        "**【라운드 종료 처리 ▸ 아군 1】**\n"
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
            "value_0": "",
            "value_type_0": "",
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
            "value_0": 5,
            "value_type_0": "정수",
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

    assert (
        body
        == "**【라운드 종료 처리 ▸ 적군 1】**\n▹ 적군 1 | -15 → 85/100 [MarkDrain: 적군 1]"
    )
    assert calc == "**【라운드 종료 처리 ▸ 적군 1】**\n▹ 적군 1 | 3[Mark] × 5 → -15"


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


def _all_allies_heal_skill(**kwargs) -> SkillData:
    return SkillData(
        id="전체 회복",
        target_rule="SkillTargetRuleAllAllies",
        target_count=0,
        cost=0,
        effects=[
            SkillEffectHeal(
                ValueSourceType.TARGET_MAX_HP, 100, ValueType.PERCENT, None, None
            )
        ],
        description="아군 전체의 체력을 최대치까지 회복한다.",
        reveal_effect=True,
        **kwargs,
    )


def test_hide_result_lines_skill_keeps_only_header_and_description_in_body():
    """hide_result_lines=True인 스킬은 본문에 "▹ 대상 | 결과" 줄을 하나도
    남기지 않는다 — 아군 전원을 한꺼번에 회복시키는 스킬은 대상 수만큼 줄이
    불어나 본문이 길이 제한에 걸리는데, 효과는 description에 이미 다 적혀
    있어 줄마다 반복할 실익이 없다. 수치는 계산식 쪽에 그대로 남는다."""
    skill = _all_allies_heal_skill(hide_result_lines=True)
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"전체 회복": skill})
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="전체 회복"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    for i, column in ((2, 1), (3, 2)):
        ctx.add_character(
            get_test_preset(f"아군 {i}", initial_hp=50),
            FactionType.ALLY,
            BattlefieldColumnIndex(column),
        )

    reply, calc = _run(ctx, manager, caster_id, "[전체 회복]")

    assert reply == (
        "**【전체 회복 ▸ 아군 1】**\n　↳ 아군 전체의 체력을 최대치까지 회복한다."
    )
    assert "▹" not in reply
    assert "▹ 아군 2 | 100 × 1[계수] → +100" in calc
    assert "▹ 아군 3 | 100 × 1[계수] → +100" in calc


def test_hide_result_lines_skill_does_not_swallow_other_parts_line_for_same_target():
    """숨김 처리는 그 스킬 파트의 본문 줄만 지운다 — 같은 커맨드의 다른
    파트가 같은 대상을 건드리면 그쪽 합산 줄은 그대로 나와야 한다. 숨긴
    파트가 합산 키를 선점해 버리면 뒤따르는 파트의 줄까지 사라진다."""
    heal_skill = _all_allies_heal_skill(hide_result_lines=True)
    single_heal = SkillData(
        id="단일 회복",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectHeal(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    ctx = BattlefieldContext(
        buff_dict={},
        skill_dict={"전체 회복": heal_skill, "단일 회복": single_heal},
    )
    manager = _ally_action_manager(ctx)
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="전체 회복", skill_2_id="단일 회복"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 2", initial_hp=50),
        FactionType.ALLY,
        BattlefieldColumnIndex(1),
    )

    reply, _calc = _run(ctx, manager, caster_id, "[전체 회복 - 단일 회복/아군 2]")

    assert "▹ 아군 2" in reply


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

    assert reply == "**【스킬\\_1 ▸ 아군 1】**\n　↳ 대상에게 고정 피해를 준다."


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

    assert reply == "**【스킬\\_1 ▸ 아군 1】**\n　↳ [효과 미확인]"


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

    # 대미지는 POST에서 정산되므로 PRE 선언 시점엔 보여줄 결과 줄이 없다 —
    # 이 경우엔 예외적으로 헤더가 커맨드 접수 확인 역할을 한다.
    assert reply == "**【스킬\\_1 ▸ 아군 1】**"


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

    assert text == "**【탈락】**\n▹ 적군 1\n▹ 적군 2"


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
