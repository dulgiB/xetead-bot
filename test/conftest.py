"""
공통 pytest fixture 모음.
각 테스트는 독립적으로 실행될 수 있도록 fixture가 매 테스트마다 새 컨텍스트를 제공한다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.round_manager import RoundManager
from battle.objects.buff.models import BuffData
from battle.objects.define import SkillTargetOverrideType, ValueSourceType, ValueType
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectDamage,
    SkillEffectHeal,
)
from battle.objects.skill.models import SkillData


@pytest.fixture
def empty_context() -> BattlefieldContext:
    """버프/스킬 없는 빈 전장 컨텍스트."""
    return BattlefieldContext(buff_dict={}, skill_dict={})


@pytest.fixture
def empty_manager(empty_context) -> RoundManager:
    return RoundManager(empty_context)


@pytest.fixture
def buff_atk_data() -> BuffData:
    return BuffData(
        id="공격력 증가",
        buff_class_name="BuffAtk",
        duration_turn_value=3,
        duration_count_value=0,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=1,
        condition_=None,
        condition_value=None,
        description="",
    )


@pytest.fixture
def skill_strong_attack() -> SkillData:
    """공격력 스탯 굴림 * 20% 대미지 스킬."""
    return SkillData(
        id="강타",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(
                ValueSourceType.STAT_ATK_ROLL, 20, ValueType.PERCENT, None, None
            )
        ],
        description="",
    )


@pytest.fixture
def skill_heal() -> SkillData:
    """고정값 10 회복 스킬."""
    return SkillData(
        id="회복",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectHeal(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None)
        ],
        description="",
    )


@pytest.fixture
def skill_add_atk_buff(buff_atk_data) -> SkillData:
    """아군에게 공격력 증가 버프를 부여하는 스킬."""
    return SkillData(
        id="공격 보조",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id="공격력 증가",
                buff_add_timing=None,
            )
        ],
        description="",
    )


@pytest.fixture
def context_with_damage_skill(skill_strong_attack) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={},
        skill_dict={"강타": skill_strong_attack},
    )


@pytest.fixture
def context_with_heal_skill(skill_heal) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={},
        skill_dict={"회복": skill_heal},
    )


@pytest.fixture
def context_with_atk_buff_skill(
    buff_atk_data, skill_add_atk_buff
) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={"공격력 증가": buff_atk_data},
        skill_dict={"공격 보조": skill_add_atk_buff},
    )


@pytest.fixture
def skill_vampiric_attack() -> SkillData:
    """적에게 고정 40 대미지를 입히고, 입힌 대미지의 50%를 자신이 회복하는 스킬."""
    return SkillData(
        id="흡혈",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 40, ValueType.INTEGER, None, None),
            SkillEffectHeal(
                ValueSourceType.GIVEN_DAMAGE,
                50,
                ValueType.PERCENT,
                None,
                None,
                SkillTargetOverrideType.SELF,
            ),
        ],
        description="",
    )


@pytest.fixture
def context_with_vampiric_skill(skill_vampiric_attack) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={},
        skill_dict={"흡혈": skill_vampiric_attack},
    )
