"""마법 저항이 어떤 대미지에 관여하는지.

마법 저항은 배율이 붙는 대미지에만 적용되고 고정 대미지(FIXED)에는 적용되지
않는다 — "N만큼 고정 대미지"라고 적은 스킬이 대상의 저항에 따라 다른 값을
내면 시트에 적은 수치와 실제가 어긋나기 때문이다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    MagicResistanceType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

SKILL_ID = "Cost2Skill"
ATTACKER = CharacterId("아군 1")
TARGET = CharacterId("적군 1")
TARGET_MAX_HP = 100


def _make_context(
    m_res: MagicResistanceType,
    value_source: ValueSourceType,
    value: int,
    value_type: ValueType,
) -> BattlefieldContext:
    skill = SkillData(
        id=SKILL_ID,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[SkillEffectDamage(value_source, value, value_type, None, None)],
        description="",
    )
    context = BattlefieldContext(buff_dict={}, skill_dict={SKILL_ID: skill})
    context.add_character(
        get_test_preset(ATTACKER.name, skill_1_id=SKILL_ID, is_magic_attacker=True),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    context.add_character(
        get_test_preset(TARGET.name, max_hp=TARGET_MAX_HP, m_res=m_res),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    return context


def _run_damage(
    m_res: MagicResistanceType,
    value_source: ValueSourceType,
    value: int,
    value_type: ValueType,
) -> int:
    context = _make_context(m_res, value_source, value, value_type)
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    manager.process_command(
        parse_character_command(ATTACKER, f"[{SKILL_ID}/{TARGET.name}]", context)
    )
    return TARGET_MAX_HP - context.characters[TARGET].status.curr_hp


@pytest.mark.parametrize("m_res", list(MagicResistanceType))
def test_magic_resistance_does_not_apply_to_fixed_damage(m_res):
    """마법 공격자가 넣는 고정 대미지는 대상의 저항과 무관하게 적힌 값 그대로다."""
    assert _run_damage(m_res, ValueSourceType.FIXED, 20, ValueType.INTEGER) == 20


@pytest.mark.parametrize(
    ("m_res", "expected"),
    [
        (MagicResistanceType.WEAK, 23),  # 20 × 1.15
        (MagicResistanceType.NORMAL, 20),
        (MagicResistanceType.STRONG, 17),  # 20 × 0.85
    ],
)
def test_magic_resistance_applies_to_scaled_damage(m_res, expected):
    """계수가 붙는 대미지에는 그대로 적용된다."""
    assert (
        _run_damage(m_res, ValueSourceType.TARGET_MAX_HP, 20, ValueType.PERCENT)
        == expected
    )
