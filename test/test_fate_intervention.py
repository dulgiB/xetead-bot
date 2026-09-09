"""운명간섭("+" 접미사) 전투 커맨드 테스트.

부활 횟수 자체의 수치 효과는 test_revival_count.py, 체력 0 캐릭터의 커맨드
차단은 test_defeated_command_block.py에서 따로 다룬다.
"""

from datetime import date, timedelta

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
from battle.objects.define import (
    FATE_INTERVENTION_ATTACK_BONUS,
    FATE_INTERVENTION_HP_COST,
    FATE_INTERVENTION_SKILL_BONUS,
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectHeal
from battle.objects.skill.models import SkillData
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import SideType
from helpers import get_test_preset

_ATTACKER = CharacterId("Catastrophe")
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


def _make_context(
    *,
    attacker_revival: int = 0,
    attacker_fate_date: str = "",
    attacker_hp: int | None = None,
    attacker_faction: FactionType = FactionType.ALLY,
    practice: bool = False,
) -> BattlefieldContext:
    skill_dict = {
        "Cost2Skill": _fixed_damage_skill("Cost2Skill", cost=2),
        "HealSkill": _heal_skill("HealSkill"),
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
        fate_date=attacker_fate_date,
        skill_1_id="Cost2Skill",
        skill_2_id="HealSkill",
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


def test_parser_marks_fate_boost_on_attack():
    """[공격+/대상]은 fate_boost=True인 파트로 파싱되어야 한다."""
    context = _make_context()
    command = parse_character_command(_ATTACKER, f"[공격+/{_TARGET.name}]", context)
    assert command is not None
    assert command.parts[0].type_ == ActionType.ATTACK
    assert command.parts[0].fate_boost is True


def test_parser_marks_fate_boost_on_skill():
    """[스킬명+/대상]도 이름과 "+"를 정확히 갈라 파싱해야 한다."""
    context = _make_context()
    command = parse_character_command(
        _ATTACKER, f"[Cost2Skill+/{_TARGET.name}]", context
    )
    assert command is not None
    assert command.parts[0].skill_id == "Cost2Skill"
    assert command.parts[0].fate_boost is True


def test_parser_keeps_fate_boost_false_without_suffix():
    """ "+"가 없으면 기존과 동일하게 fate_boost=False여야 한다."""
    context = _make_context()
    command = parse_character_command(_ATTACKER, f"[공격/{_TARGET.name}]", context)
    assert command is not None
    assert command.parts[0].fate_boost is False


# ── 운명간섭: 사용 조건 ──────────────────────────────────────────────────────


def test_fate_requires_revival_experience():
    """부활 경험이 없으면 운명간섭을 쓸 수 없다."""
    context = _make_context(attacker_revival=0)
    with pytest.raises(CommandValidationError, match="부활 횟수"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_fate_blocked_when_used_today():
    """시트의 fate_date가 오늘이면 거부한다."""
    context = _make_context(
        attacker_revival=1, attacker_fate_date=date.today().isoformat()
    )
    with pytest.raises(CommandValidationError, match="이미 사용"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_fate_allowed_when_used_on_another_day():
    """어제 썼다면 오늘은 다시 쓸 수 있다 — 별도 리셋 절차가 필요 없다."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    context = _make_context(attacker_revival=1, attacker_fate_date=yesterday)
    _run(context, f"[공격+/{_TARGET.name}]")
    assert context.characters[_ATTACKER].fate_used is True


def test_fate_blocked_when_hp_not_above_cost():
    """체력이 소모량 이하면 거부한다 — 운명간섭으로 자멸하지 않게 한다."""
    context = _make_context(attacker_revival=1, attacker_hp=FATE_INTERVENTION_HP_COST)
    with pytest.raises(CommandValidationError, match="체력"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_fate_blocked_on_non_damage_skill():
    """비대미지 스킬에는 붙일 수 없다 (초기 구현 범위 밖)."""
    context = _make_context(attacker_revival=1)
    with pytest.raises(CommandValidationError, match="대미지를 주지 않아"):
        _run(context, f"[HealSkill+/{_ATTACKER.name}]")


def test_fate_blocked_twice_in_one_command():
    """1회 제한 자원이므로 한 커맨드에 두 번 붙일 수 없다."""
    context = _make_context(attacker_revival=1)
    with pytest.raises(CommandValidationError, match="하나의 행동에만"):
        _run(context, f"[공격+/{_TARGET.name} - 공격+/{_TARGET.name}]")


def test_fate_blocked_in_practice_battle():
    """대련/상시전투는 임시 캐릭터로 진행하므로 운명간섭을 쓸 수 없다."""
    context = _make_context(attacker_revival=1, practice=True)
    with pytest.raises(CommandValidationError, match="사용할 수 없습니다"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_failed_fate_command_consumes_nothing():
    """검증에 걸린 운명간섭 커맨드는 체력도 코스트도 소모하지 않아야 한다."""
    context = _make_context(attacker_revival=0)
    attacker = context.characters[_ATTACKER]
    hp_before = attacker.status.curr_hp
    cost_before = attacker.status.remaining_cost

    with pytest.raises(CommandValidationError):
        _run(context, f"[공격+/{_TARGET.name}]")

    assert attacker.status.curr_hp == hp_before
    assert attacker.status.remaining_cost == cost_before
    assert attacker.fate_used is False


# ── 운명간섭: 실제 효과 ──────────────────────────────────────────────────────


def test_fate_attack_costs_hp_and_marks_used():
    """운명간섭 공격은 체력을 소모하고 "사용함"으로 표시되어야 한다."""
    context = _make_context(attacker_revival=1)
    attacker = context.characters[_ATTACKER]
    hp_before = attacker.status.curr_hp

    _run(context, f"[공격+/{_TARGET.name}]")

    assert attacker.status.curr_hp == hp_before - FATE_INTERVENTION_HP_COST
    assert attacker.fate_used is True


def test_fate_hp_cost_is_logged_for_sheet_write_back():
    """체력 소모가 대미지 로그로 남아야 시트 체력 반영 경로를 탄다."""
    context = _make_context(attacker_revival=1)
    result = _run(context, f"[공격+/{_TARGET.name}]")

    entries = [e for part in result.part_results for e in part.log_entries]
    fate_entries = [e for e in entries if "운명간섭" in e.source_labels]
    assert len(fate_entries) == 1
    entry = fate_entries[0]
    assert entry.kind == BattleLogEntryKind.DAMAGE
    assert entry.target_name == _ATTACKER.name
    assert entry.value == FATE_INTERVENTION_HP_COST
    # write_back_changed_hp()가 이 접두사로 대상을 추린다.
    assert entry.result.startswith("대미지 ")


def test_fate_second_use_blocked_within_same_battle():
    """한 전투 안에서 두 번째 운명간섭은 시트 반영과 무관하게 막혀야 한다."""
    context = _make_context(attacker_revival=1)
    _run(context, f"[공격+/{_TARGET.name}]")
    context.on_start_round()  # 코스트 회복
    with pytest.raises(CommandValidationError, match="이미 사용"):
        _run(context, f"[공격+/{_TARGET.name}]")


def test_fate_attack_bonus_is_added_before_multipliers():
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
    assert f"+{FATE_INTERVENTION_ATTACK_BONUS}[운명간섭]" in (
        damage_entries[0].roll_display or ""
    )


def test_fate_skill_bonus_applies_to_fixed_damage():
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
    assert damage_entries[0].value == _FIXED_DAMAGE + FATE_INTERVENTION_SKILL_BONUS


# ── 운명간섭: 적군 선언 경로 ────────────────────────────────────────────────


def test_fate_cost_applied_on_enemy_pre_declaration():
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

    assert declarer.status.curr_hp == hp_before - FATE_INTERVENTION_HP_COST
    assert declarer.fate_used is True

    # POST 재전개로 대가가 한 번 더 빠지지 않아야 한다.
    try_process_enemy_command_on_post_action(context, _ATTACKER, remaining[_ATTACKER])
    assert declarer.status.curr_hp == hp_before - FATE_INTERVENTION_HP_COST
