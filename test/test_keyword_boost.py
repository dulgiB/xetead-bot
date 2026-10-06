"""키워드 보정("+" 접미사) 전투 커맨드 테스트.

부활 횟수 자체의 수치 효과는 test_revival_count.py, 체력 0 캐릭터의 커맨드
차단은 test_defeated_command_block.py에서 따로 다룬다.
"""

from datetime import date, timedelta

import battle.core.command_processors as command_processors_module
import battle.objects.character.combat_character as combat_character_module
import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import (
    process_ally_command,
    process_enemy_command_on_pre_action,
    try_process_enemy_command_on_post_action,
)
from battle.core.commands.models import BattleLogEntryKind
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    KEYWORD_BOOST_ATTACK_BONUS,
    KEYWORD_BOOST_HP_COST,
    KEYWORD_BOOST_SKILL_BONUS,
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectConsumeStackForDamage,
    SkillEffectDamage,
    SkillEffectHeal,
)
from battle.objects.skill.models import SkillData
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import SideType
from helpers import get_test_preset

_ATTACKER = CharacterId("Bearer")
_TARGET = CharacterId("Adversary")


_FIXED_DAMAGE = 30


def _fixed_damage_skill(
    skill_id: str, cost: int, damage: int = _FIXED_DAMAGE
) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=cost,
        effects=[
            SkillEffectDamage(
                ValueSourceType.FIXED, damage, ValueType.INTEGER, None, None
            )
        ],
        description="",
    )


def _heal_skill(skill_id: str, cost: int = 2) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=cost,
        effects=[
            SkillEffectHeal(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None)
        ],
        description="",
    )


def _hp_ratio_damage_skill(skill_id: str) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(
                ValueSourceType.TARGET_MAX_HP, 10, ValueType.PERCENT, None, None
            )
        ],
        description="",
    )


def _make_context(
    *,
    attacker_revival: int = 0,
    attacker_keyword_date: str = "",
    attacker_hp: int | None = None,
    attacker_faction: FactionType = FactionType.ALLY,
    practice: bool = False,
) -> BattlefieldContext:
    skill_dict = {
        "Cost2Skill": _fixed_damage_skill("Cost2Skill", cost=2),
        "HealSkill": _heal_skill("HealSkill"),
        "HpRatioSkill": _hp_ratio_damage_skill("HpRatioSkill"),
    }
    context: BattlefieldContext
    if practice:
        context = PracticeBattlefieldContext(buff_dict={}, skill_dict=skill_dict)
    else:
        context = BattlefieldContext(buff_dict={}, skill_dict=skill_dict)

    attacker = get_test_preset(
        _ATTACKER.name,
        initial_hp=attacker_hp,
        revival_count=attacker_revival,
        keyword_date=attacker_keyword_date,
        skill_1_id="Cost2Skill",
        skill_2_id="HealSkill",
        skill_3_id="HpRatioSkill",
    )
    target = get_test_preset(_TARGET.name)

    if practice:
        assert isinstance(context, PracticeBattlefieldContext)
        context.add_character(attacker, SideType.SIDE_1, BattlefieldColumnIndex(3))
        context.add_character(target, SideType.SIDE_2, BattlefieldColumnIndex(3))
    else:
        context.add_character(attacker, attacker_faction, BattlefieldColumnIndex(3))
        context.add_character(target, FactionType.ENEMY, BattlefieldColumnIndex(3))
    return context


def _run(context: BattlefieldContext, text: str):
    command = parse_character_command(_ATTACKER, text, context)
    assert command is not None
    return process_ally_command(context, command)


# ── 파서 ────────────────────────────────────────────────────────────────────


def test_parser_marks_keyword_boost_on_attack():
    """[공격+/대상]은 keyword_boost=True인 파트로 파싱되어야 한다."""
    context = _make_context()
    command = parse_character_command(_ATTACKER, f"[공격+/{_TARGET.name}]", context)
    assert command is not None
    assert command.parts[0].type_ == ActionType.ATTACK
    assert command.parts[0].keyword_boost is True


def test_parser_marks_keyword_boost_on_skill():
    """[스킬명+/대상]도 이름과 "+"를 정확히 갈라 파싱해야 한다."""
    context = _make_context()
    command = parse_character_command(
        _ATTACKER, f"[Cost2Skill+/{_TARGET.name}]", context
    )
    assert command is not None
    assert command.parts[0].skill_id == "Cost2Skill"
    assert command.parts[0].keyword_boost is True


def test_parser_keeps_keyword_boost_false_without_suffix():
    """ "+"가 없으면 기존과 동일하게 keyword_boost=False여야 한다."""
    context = _make_context()
    command = parse_character_command(_ATTACKER, f"[공격/{_TARGET.name}]", context)
    assert command is not None
    assert command.parts[0].keyword_boost is False


# ── 키워드 보정: 사용 조건 ──────────────────────────────────────────────────────


def test_keyword_requires_revival_experience():
    """부활 경험이 없으면 키워드 보정을 쓸 수 없다."""
    context = _make_context(attacker_revival=0)
    with pytest.raises(CommandValidationError, match="부활 횟수"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_keyword_blocked_when_used_today():
    """시트의 keyword_date가 오늘이면 거부한다."""
    context = _make_context(
        attacker_revival=1, attacker_keyword_date=date.today().isoformat()
    )
    with pytest.raises(CommandValidationError, match="이미 사용"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_keyword_allowed_when_used_on_another_day():
    """어제 썼다면 오늘은 다시 쓸 수 있다 — 별도 리셋 절차가 필요 없다."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    context = _make_context(attacker_revival=1, attacker_keyword_date=yesterday)
    _run(context, f"[공격+/{_TARGET.name}]")
    assert context.characters[_ATTACKER].keyword_used is True


def test_keyword_blocked_when_hp_not_above_cost():
    """체력이 소모량 이하면 거부한다 — 키워드 보정으로 자멸하지 않게 한다."""
    context = _make_context(attacker_revival=1, attacker_hp=KEYWORD_BOOST_HP_COST)
    with pytest.raises(CommandValidationError, match="체력"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_keyword_blocked_on_non_damage_skill():
    """keyword_mode를 지정하지 않은 비대미지 스킬에는 붙일 수 없다.

    시트에 keyword_mode를 채운 비대미지 스킬은 반대로 허용된다 —
    test_keyword_boost_modes.py 참고.
    """
    context = _make_context(attacker_revival=1)
    with pytest.raises(CommandValidationError, match="보정을 받을 대미지가 없고"):
        _run(context, f"[HealSkill+/{_ATTACKER.name}]")


def test_keyword_blocked_twice_in_one_command():
    """1회 제한 자원이므로 한 커맨드에 두 번 붙일 수 없다."""
    context = _make_context(attacker_revival=1)
    with pytest.raises(CommandValidationError, match="하나의 행동에만"):
        _run(context, f"[공격+/{_TARGET.name} - 공격+/{_TARGET.name}]")


def test_keyword_blocked_in_practice_battle():
    """대련/상시전투는 임시 캐릭터로 진행하므로 키워드 보정을 쓸 수 없다."""
    context = _make_context(attacker_revival=1, practice=True)
    with pytest.raises(CommandValidationError, match="사용할 수 없습니다"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_failed_keyword_command_consumes_nothing():
    """검증에 걸린 키워드 보정 커맨드는 체력도 코스트도 소모하지 않아야 한다."""
    context = _make_context(attacker_revival=0)
    attacker = context.characters[_ATTACKER]
    hp_before = attacker.status.curr_hp
    cost_before = attacker.status.remaining_cost

    with pytest.raises(CommandValidationError):
        _run(context, f"[공격+/{_TARGET.name}]")

    assert attacker.status.curr_hp == hp_before
    assert attacker.status.remaining_cost == cost_before
    assert attacker.keyword_used is False


# ── 키워드 보정: 실제 효과 ──────────────────────────────────────────────────────


def test_keyword_attack_costs_hp_and_marks_used():
    """키워드 보정 공격은 체력을 소모하고 "사용함"으로 표시되어야 한다."""
    context = _make_context(attacker_revival=1)
    attacker = context.characters[_ATTACKER]
    hp_before = attacker.status.curr_hp

    _run(context, f"[공격+/{_TARGET.name}]")

    assert attacker.status.curr_hp == hp_before - KEYWORD_BOOST_HP_COST
    assert attacker.keyword_used is True


def test_keyword_hp_cost_is_logged_for_sheet_write_back():
    """체력 소모가 대미지 로그로 남아야 시트 체력 반영 경로를 탄다."""
    context = _make_context(attacker_revival=1)
    result = _run(context, f"[공격+/{_TARGET.name}]")

    entries = [e for part in result.part_results for e in part.log_entries]
    keyword_entries = [e for e in entries if "키워드 보정" in e.source_labels]
    assert len(keyword_entries) == 1
    entry = keyword_entries[0]
    assert entry.kind == BattleLogEntryKind.DAMAGE
    assert entry.target_name == _ATTACKER.name
    assert entry.value == KEYWORD_BOOST_HP_COST
    # write_back_changed_hp()가 이 접두사로 대상을 추린다.
    assert entry.result.startswith("대미지 ")


def test_keyword_second_use_blocked_within_same_battle():
    """한 전투 안에서 두 번째 키워드 보정은 시트 반영과 무관하게 막혀야 한다."""
    context = _make_context(attacker_revival=1)
    _run(context, f"[공격+/{_TARGET.name}]")
    context.on_start_round()  # 코스트 회복
    with pytest.raises(CommandValidationError, match="이미 사용"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_keyword_unblocked_after_midnight_within_same_battle(monkeypatch):
    """며칠 이어지는 전투(결투/상시전투)에서도 자정이 지나면 다시 쓸 수 있다."""
    context = _make_context(attacker_revival=1)
    _run(context, f"[공격+/{_TARGET.name}]")

    tomorrow = date.today() + timedelta(days=1)

    class _Tomorrow(date):
        @classmethod
        def today(cls):
            return tomorrow

    monkeypatch.setattr(combat_character_module, "date", _Tomorrow)
    monkeypatch.setattr(command_processors_module, "date", _Tomorrow)
    context.on_start_round()  # 코스트 회복
    assert context.characters[_ATTACKER].keyword_used is False
    _run(context, f"[공격+/{_TARGET.name}]")
    assert context.characters[_ATTACKER].keyword_date == tomorrow.isoformat()


def test_keyword_empty_date_is_never_used():
    """빈 keyword_date는 어떤 날짜와도 일치하지 않아야 한다."""
    context = _make_context(attacker_revival=1)
    assert context.characters[_ATTACKER].keyword_used is False


def test_keyword_attack_bonus_is_added_before_multipliers():
    """공격 굴림 보정은 배율보다 먼저 더해지는 IntValueModifier여야 한다."""
    context = _make_context(attacker_revival=1)
    result = _run(context, f"[공격+/{_TARGET.name}]")

    damage_entries = [
        e
        for part in result.part_results
        for e in part.log_entries
        if e.kind == BattleLogEntryKind.DAMAGE and e.target_name == _TARGET.name
    ]
    assert len(damage_entries) == 1
    assert f"+{KEYWORD_BOOST_ATTACK_BONUS}[키워드 보정]" in (
        damage_entries[0].roll_display or ""
    )


def test_keyword_skill_bonus_applies_to_fixed_damage():
    """FIXED 대미지 스킬에도 보정이 그대로 더해져야 한다 (조용히 사라지지 않는다)."""
    context = _make_context(attacker_revival=1)
    result = _run(context, f"[Cost2Skill+/{_TARGET.name}]")

    damage_entries = [
        e
        for part in result.part_results
        for e in part.log_entries
        if e.kind == BattleLogEntryKind.DAMAGE and e.target_name == _TARGET.name
    ]
    assert len(damage_entries) == 1
    assert damage_entries[0].value == _FIXED_DAMAGE + KEYWORD_BOOST_SKILL_BONUS


_STACK_BUFF_ID = "StackBuff"
_STACK_DAMAGE_PERCENT = 500


def _make_stack_skill_context(holder_stack: int) -> BattlefieldContext:
    """굴림 대미지 + "소모한 스택 수 × 계수" 고정 대미지를 함께 주는 스킬."""
    stack_buff = BuffData(
        id=_STACK_BUFF_ID,
        description="",
        buff_class_name="BuffBattleEndPenalty",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=None,
        value=0,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.NEUTRAL,
        max_stack=10,
    )
    skill = SkillData(
        id="StackSkill",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(
                ValueSourceType.FIXED, _FIXED_DAMAGE, ValueType.INTEGER, None, None
            ),
            SkillEffectConsumeStackForDamage(
                value_source=ValueSourceType.CONSUMED_BUFF_STACK,
                value=_STACK_DAMAGE_PERCENT,
                value_type=ValueType.PERCENT,
                buff_id=_STACK_BUFF_ID,
                buff_add_timing=None,
                buff_stack_cap=5,
            ),
        ],
        description="",
    )
    context = BattlefieldContext(
        buff_dict={_STACK_BUFF_ID: stack_buff}, skill_dict={"StackSkill": skill}
    )
    context.add_character(
        get_test_preset(_ATTACKER.name, revival_count=1, skill_1_id="StackSkill"),
        FactionType.ALLY,
        BattlefieldColumnIndex(3),
    )
    context.add_character(
        get_test_preset(_TARGET.name, max_hp=300),
        FactionType.ENEMY,
        BattlefieldColumnIndex(3),
    )
    if holder_stack > 0:
        context.buff_container.add(
            BuffAddData(
                given_by=_ATTACKER,
                applied_to=_ATTACKER,
                buff_id=_STACK_BUFF_ID,
                stack_value=holder_stack,
            )
        )
    return context


@pytest.mark.parametrize("holder_stack", [0, 2])
def test_keyword_roll_bonus_skips_stack_proportional_damage(holder_stack):
    context = _make_stack_skill_context(holder_stack)
    hp_before = context.characters[_TARGET].status.curr_hp
    _run(context, f"[StackSkill+/{_TARGET.name}]")

    stack_damage = holder_stack * _STACK_DAMAGE_PERCENT // 100
    assert (
        hp_before - context.characters[_TARGET].status.curr_hp
        == _FIXED_DAMAGE + KEYWORD_BOOST_SKILL_BONUS + stack_damage
    )


def test_keyword_blocked_on_skill_without_roll_damage():
    context = _make_context(attacker_revival=1)
    with pytest.raises(CommandValidationError, match="보정을 받을 대미지가 없고"):
        _run(context, f"[HpRatioSkill+/{_TARGET.name}]")


# ── 키워드 보정: 적군 선언 경로 ────────────────────────────────────────────────


def test_keyword_cost_applied_on_enemy_pre_declaration():
    """적군 진영에 배치된 캐릭터 시트 출신 캐릭터도 선언 시점에 대가를 낸다.

    적군 커맨드는 PRE에서 선언하고 POST에서 정산하는 구조라, 대가를 PRE에서
    처리하지 않으면 그대로 공짜가 되거나 POST 재전개마다 중복 소모된다.
    """
    context = _make_context(attacker_revival=1, attacker_faction=FactionType.ENEMY)
    declarer = context.characters[_ATTACKER]
    hp_before = declarer.status.curr_hp

    command = parse_character_command(_ATTACKER, f"[공격+/{_TARGET.name}]", context)
    assert command is not None
    remaining: dict = {}
    process_enemy_command_on_pre_action(context, command, remaining)

    assert declarer.status.curr_hp == hp_before - KEYWORD_BOOST_HP_COST
    assert declarer.keyword_used is True

    # POST 재전개로 대가가 한 번 더 빠지지 않아야 한다.
    try_process_enemy_command_on_post_action(context, _ATTACKER, remaining[_ATTACKER])
    assert declarer.status.curr_hp == hp_before - KEYWORD_BOOST_HP_COST
