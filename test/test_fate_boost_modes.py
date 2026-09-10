"""스킬별 키워드 보정 모드("스킬_캐릭터" 시트 fate_mode) 테스트.

fate_mode를 비워 둔 스킬의 기존 동작(대미지 굴림 보정)은
test_fate_intervention.py가 다룬다 — 여기서는 시트에 모드를 지정했을 때만
생기는 동작을 검증한다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import process_ally_command
from battle.core.commands.models import BattleLogEntryKind
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    BattlefieldColumnIndex,
    FactionType,
    FateBoostMode,
    ValueSourceType,
    ValueType,
)
from battle.objects.skill.define import SkillValueType
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectDamage,
    SkillEffectHeal,
)
from battle.objects.skill.models import SkillData, fate_config_error
from helpers import get_test_preset

_CASTER = CharacterId("Catastrophe")
_TARGET = CharacterId("Adversary")
_ALLY = CharacterId("Companion")

_BUFF_ID = "PassiveBuff"
_BUFF_VALUE = 5


def _buff_data(max_stack: int | None = None) -> BuffData:
    return BuffData(
        id=_BUFF_ID,
        buff_class_name="BuffAtk",
        duration_turn_value=3,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=_BUFF_VALUE,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
        max_stack=max_stack,
    )


def _skill(
    skill_id: str,
    *,
    effects: list,
    target_rule: str = "SkillTargetRuleNamed",
    target_count: int = 1,
    cost: int = 2,
    fate_mode: FateBoostMode | None = None,
    fate_value: int | None = None,
    fate_effect_index: int = 0,
) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule=target_rule,
        target_count=target_count,
        cost=cost,
        effects=effects,
        description="",
        fate_mode=fate_mode,
        fate_value=fate_value,
        fate_effect_index=fate_effect_index,
    )


def _make_context(skill: SkillData, *, buff: BuffData | None = None):
    context = BattlefieldContext(
        buff_dict={_BUFF_ID: buff} if buff is not None else {},
        skill_dict={skill.id: skill},
    )
    context.add_character(
        get_test_preset(_CASTER.name, revival_count=1, skill_1_id=skill.id),
        FactionType.ALLY,
        BattlefieldColumnIndex(3),
    )
    context.add_character(
        get_test_preset(_TARGET.name), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )
    context.add_character(
        get_test_preset(_ALLY.name), FactionType.ALLY, BattlefieldColumnIndex(4)
    )
    return context


def _run(context: BattlefieldContext, text: str):
    command = parse_character_command(_CASTER, text, context)
    assert command is not None
    return process_ally_command(context, command)


def _damage_entries(result, target_name: str = _TARGET.name):
    """대상에게 들어간 대미지 로그만 추린다.

    키워드 보정의 체력 20 소모도 시전자 대상의 DAMAGE 엔트리로 남으므로
    (write_back_changed_hp()가 그 경로를 타야 한다), 대상 이름으로 걸러야
    스킬 대미지만 본다."""
    return [
        entry
        for part in result.part_results
        for entry in part.log_entries
        if entry.kind == BattleLogEntryKind.DAMAGE and entry.target_name == target_name
    ]


def _heal_entries(result):
    return [
        entry
        for part in result.part_results
        for entry in part.log_entries
        if entry.kind == BattleLogEntryKind.HEAL
    ]


# ── 수치 강화 ───────────────────────────────────────────────────────────────


def test_value_boost_adds_percentage_points_to_coefficient():
    """퍼센트 효과는 계수에 %p로 더해진다 — 배율을 한 번 더 곱하지 않는다.

    ATK 5 + 굴림 1 = 6, 계수 100% + 50%p = 150% → 9.
    배율을 곱하는 방식이었다면 6 × 1.0 × 1.5 = 9로 같지만, 계수가 100%가
    아닐 때 차이가 난다 — 아래 test_value_boost_is_not_multiplicative가 그
    경우를 고정한다.
    """
    skill = _skill(
        "Cost2Skill",
        effects=[
            SkillEffectDamage(
                ValueSourceType.STAT_ATK_ROLL, 100, SkillValueType.PERCENT, None, None
            )
        ],
        fate_mode=FateBoostMode.VALUE_BOOST,
        fate_value=50,
    )
    context = _make_context(skill)
    result = _run(context, f"[Cost2Skill+/{_TARGET.name}]")

    entries = _damage_entries(result)
    assert len(entries) == 1
    assert "[계수+키워드 보정]" in (entries[0].roll_display or "")


def test_value_boost_is_not_multiplicative():
    """계수 200%에 +50%p면 250%여야 한다(200%×150%=300%가 아니라)."""
    skill = _skill(
        "Cost2Skill",
        effects=[
            SkillEffectDamage(
                ValueSourceType.STAT_ATK_ROLL, 200, SkillValueType.PERCENT, None, None
            )
        ],
        fate_mode=FateBoostMode.VALUE_BOOST,
        fate_value=50,
    )
    context = _make_context(skill)
    result = _run(context, f"[Cost2Skill+/{_TARGET.name}]")

    entries = _damage_entries(result)
    assert len(entries) == 1
    assert "× 2.5[계수+키워드 보정]" in (entries[0].roll_display or "")


def test_value_boost_adds_flat_value_to_integer_heal():
    """정수 효과(회복량 등)에는 정수 그대로 더해진다."""
    skill = _skill(
        "HealSkill",
        effects=[
            SkillEffectHeal(
                ValueSourceType.FIXED, 10, SkillValueType.INTEGER, None, None
            )
        ],
        fate_mode=FateBoostMode.VALUE_BOOST,
        fate_value=15,
    )
    context = _make_context(skill)
    context.characters[_ALLY].status.curr_hp = 10
    result = _run(context, f"[HealSkill+/{_ALLY.name}]")

    entries = _heal_entries(result)
    assert len(entries) == 1
    assert entries[0].value == 10 + 15


def test_value_boost_targets_only_the_indexed_effect():
    """fate_effect_index가 가리키는 효과에만 보정이 걸린다.

    같은 대상에게 들어간 대미지는 로그 한 줄로 합산되므로(build_log_entries),
    합계를 "+"를 붙이지 않은 경우와 비교해 보정이 한 효과에만 들어갔는지 본다.
    """
    skill = _skill(
        "Cost3Skill",
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None),
            SkillEffectDamage(ValueSourceType.FIXED, 30, ValueType.INTEGER, None, None),
        ],
        cost=3,
        fate_mode=FateBoostMode.VALUE_BOOST,
        fate_value=7,
        fate_effect_index=1,
    )
    boosted_total = sum(
        entry.value
        for entry in _damage_entries(
            _run(_make_context(skill), f"[Cost3Skill+/{_TARGET.name}]")
        )
    )
    plain_total = sum(
        entry.value
        for entry in _damage_entries(
            _run(_make_context(skill), f"[Cost3Skill/{_TARGET.name}]")
        )
    )
    assert plain_total == 20 + 30
    assert boosted_total == 20 + 30 + 7


# ── 버프 강화 ───────────────────────────────────────────────────────────────


def test_buff_value_boost_overrides_buff_sheet_value():
    """버프 수치 강화는 버프 시트 수치에 보정을 더해 부여한다."""
    skill = _skill(
        "PassiveSkill",
        effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
        fate_mode=FateBoostMode.BUFF_VALUE_BOOST,
        fate_value=4,
    )
    context = _make_context(skill, buff=_buff_data())
    _run(context, f"[PassiveSkill+/{_ALLY.name}]")

    buff = context.buff_container.get_buff(_ALLY, _BUFF_ID)
    assert buff is not None
    assert buff.value == _BUFF_VALUE + 4


def test_buff_stack_boost_adds_stacks():
    """버프 스택 강화는 한 번에 쌓이는 스택 수를 늘린다."""
    skill = _skill(
        "PassiveSkill",
        effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
        fate_mode=FateBoostMode.BUFF_STACK_BOOST,
        fate_value=2,
    )
    context = _make_context(skill, buff=_buff_data(max_stack=5))
    _run(context, f"[PassiveSkill+/{_ALLY.name}]")

    buff = context.buff_container.get_buff(_ALLY, _BUFF_ID)
    assert buff is not None
    assert buff.stack_count == 1 + 2


def test_buff_boost_does_not_apply_without_fate_suffix():
    """ "+"를 붙이지 않으면 버프는 시트 그대로 부여된다."""
    skill = _skill(
        "PassiveSkill",
        effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
        fate_mode=FateBoostMode.BUFF_VALUE_BOOST,
        fate_value=4,
    )
    context = _make_context(skill, buff=_buff_data())
    _run(context, f"[PassiveSkill/{_ALLY.name}]")

    buff = context.buff_container.get_buff(_ALLY, _BUFF_ID)
    assert buff is not None
    assert buff.value == _BUFF_VALUE


# ── 대상 추가 ───────────────────────────────────────────────────────────────


def test_extra_target_allows_one_more_target_with_fate_suffix():
    """대상 추가 모드는 "+"를 붙였을 때만 대상을 하나 더 받는다."""
    skill = _skill(
        "PassiveSkill",
        effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
        fate_mode=FateBoostMode.EXTRA_TARGET,
        fate_value=1,
    )
    context = _make_context(skill, buff=_buff_data())
    _run(context, f"[PassiveSkill+/{_ALLY.name}/{_CASTER.name}]")

    assert context.buff_container.get_buff(_ALLY, _BUFF_ID) is not None
    assert context.buff_container.get_buff(_CASTER, _BUFF_ID) is not None


def test_extra_target_rejected_without_fate_suffix():
    """ "+" 없이 대상을 더 적으면 기존대로 target_count 초과로 거부된다."""
    skill = _skill(
        "PassiveSkill",
        effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
        fate_mode=FateBoostMode.EXTRA_TARGET,
        fate_value=1,
    )
    context = _make_context(skill, buff=_buff_data())
    with pytest.raises(CommandValidationError):
        _run(context, f"[PassiveSkill/{_ALLY.name}/{_CASTER.name}]")


# ── 비대미지 스킬 허용 여부 ─────────────────────────────────────────────────


def test_non_damage_skill_with_mode_is_allowed():
    """모드를 지정한 비대미지 스킬은 더 이상 거부되지 않는다."""
    skill = _skill(
        "PassiveSkill",
        effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
        fate_mode=FateBoostMode.BUFF_VALUE_BOOST,
        fate_value=1,
    )
    context = _make_context(skill, buff=_buff_data())
    _run(context, f"[PassiveSkill+/{_ALLY.name}]")  # 예외가 나지 않아야 한다


def test_non_damage_skill_without_mode_is_still_rejected():
    """모드를 비워 둔 비대미지 스킬은 예전처럼 거부된다."""
    skill = _skill(
        "PassiveSkill",
        effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
    )
    context = _make_context(skill, buff=_buff_data())
    with pytest.raises(CommandValidationError, match="대미지를 주지 않고"):
        _run(context, f"[PassiveSkill+/{_ALLY.name}]")


# ── 시트 설정 검증 ──────────────────────────────────────────────────────────


def test_fate_config_error_none_when_mode_empty():
    assert fate_config_error(_skill("Cost2Skill", effects=[])) is None


def test_fate_config_error_requires_value():
    error = fate_config_error(
        _skill(
            "Cost2Skill",
            effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
            fate_mode=FateBoostMode.BUFF_STACK_BOOST,
        )
    )
    assert error is not None and "fate_value가 비어 있습니다" in error


def test_fate_config_error_rejects_extra_target_on_self_rule():
    error = fate_config_error(
        _skill(
            "PassiveSkill",
            effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
            target_rule="SkillTargetRuleSelf",
            fate_mode=FateBoostMode.EXTRA_TARGET,
            fate_value=1,
        )
    )
    assert error is not None and "대상을 입력받지 않아" in error


def test_fate_config_error_rejects_buff_mode_on_non_buff_effect():
    error = fate_config_error(
        _skill(
            "Cost2Skill",
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
                )
            ],
            fate_mode=FateBoostMode.BUFF_VALUE_BOOST,
            fate_value=3,
        )
    )
    assert error is not None and "버프를 부여하지 않아" in error


def test_fate_config_error_rejects_missing_effect_index():
    error = fate_config_error(
        _skill(
            "Cost2Skill",
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
                )
            ],
            fate_mode=FateBoostMode.VALUE_BOOST,
            fate_value=3,
            fate_effect_index=2,
        )
    )
    assert error is not None and "effect_2" in error


def test_fate_config_error_accepts_valid_config():
    assert (
        fate_config_error(
            _skill(
                "PassiveSkill",
                effects=[SkillEffectAddBuff(None, None, None, _BUFF_ID, None)],
                fate_mode=FateBoostMode.BUFF_VALUE_BOOST,
                fate_value=3,
            )
        )
        is None
    )
