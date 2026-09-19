"""대상별 조건과 조건 이탈 시 회수(기믹 3).

패시브 파이프라인의 condition은 effect당 한 번, holder 기준으로만 평가되므로
"체력 N% 이하인 대상에게만"을 표현할 자리가 없었다. 대상별 조건은 조건
클래스를 그대로 재사용하되 holder 자리에 각 대상을 넣어 평가한다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueType,
)
from battle.objects.field_effect.models import FieldEffectSource
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectConditionalBuff,
)
from helpers import get_test_preset

BUFF_ID = "ConditionalBuff"
EFFECT_ID = "FieldEffect"


def _buff() -> BuffData:
    return BuffData(
        id=BUFF_ID,
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=10,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.BUFF,
        description="",
    )


def _effect(
    effect_class=SkillEffectConditionalBuff,
    condition_class_name: str = "SelfHpBelowCondition",
    condition_value: int = 50,
) -> PassiveSkillData:
    return PassiveSkillData(
        id=EFFECT_ID,
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=PassiveSkillTargetType.FIELD_ALLY_SIDE,
        effects=[
            effect_class(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=BUFF_ID,
                buff_add_timing=None,
                target_condition_class_name=condition_class_name,
                target_condition_value=condition_value,
            )
        ],
        description="",
    )


def _make_context(effect: PassiveSkillData) -> BattlefieldContext:
    ctx = BattlefieldContext(
        buff_dict={BUFF_ID: _buff()},
        skill_dict={},
        passive_skill_dict={effect.id: effect},
    )
    ctx.add_character(
        get_test_preset("건강", max_hp=100, initial_hp=100),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("부상", max_hp=100, initial_hp=30),
        FactionType.ALLY,
        BattlefieldColumnIndex(1),
    )
    return ctx


def _has_buff(ctx: BattlefieldContext, name: str) -> bool:
    return ctx.buff_container.get_buff(CharacterId(name), BUFF_ID) is not None


def _set_hp(ctx: BattlefieldContext, name: str, hp: int) -> None:
    ctx.characters[CharacterId(name)].status.curr_hp = hp


class TestTargetCondition:
    def test_only_matching_targets_are_buffed(self):
        ctx = _make_context(_effect())
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert _has_buff(ctx, "부상")
        assert not _has_buff(ctx, "건강")

    def test_condition_is_evaluated_per_target_for_plain_add_buff_too(self):
        """대상별 조건은 조건부 버프 전용이 아니다 — 일반 부여 효과에도
        같은 필터가 걸린다."""
        ctx = _make_context(_effect(SkillEffectAddBuff))
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert _has_buff(ctx, "부상")
        assert not _has_buff(ctx, "건강")

    def test_target_becoming_eligible_is_buffed_next_evaluation(self):
        ctx = _make_context(_effect())
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.on_start_round()
        assert not _has_buff(ctx, "건강")

        _set_hp(ctx, "건강", 20)
        ctx.on_start_round()

        assert _has_buff(ctx, "건강")


class TestRevokeOnConditionExit:
    def test_buff_is_revoked_when_target_leaves_the_condition(self):
        ctx = _make_context(_effect())
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.on_start_round()
        assert _has_buff(ctx, "부상")

        _set_hp(ctx, "부상", 90)
        ctx.on_start_round()

        assert not _has_buff(ctx, "부상")

    def test_plain_add_buff_does_not_revoke(self):
        """부여만 하는 효과는 조건에서 벗어나도 풀리지 않는다 — 회수가
        필요하면 조건부 버프 효과를 써야 한다는 것을 고정해 둔다."""
        ctx = _make_context(_effect(SkillEffectAddBuff))
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.on_start_round()

        _set_hp(ctx, "부상", 90)
        ctx.on_start_round()

        assert _has_buff(ctx, "부상")

    def test_buff_from_another_source_is_not_revoked(self):
        """회수는 이 효과가 건 인스턴스만 지운다."""
        ctx = _make_context(_effect())
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.on_start_round()

        other = CharacterId("건강")
        ctx.buff_container.add(
            BuffAddData(
                given_by=other,
                applied_to=CharacterId("부상"),
                buff_id=BUFF_ID,
            )
        )
        _set_hp(ctx, "부상", 90)
        ctx.on_start_round()

        assert (
            ctx.buff_container.get_buff(CharacterId("부상"), BUFF_ID, given_by=other)
            is not None
        )


class TestHpConditionVariants:
    def test_at_least_ratio(self):
        ctx = _make_context(_effect(condition_class_name="SelfHpAtLeastCondition"))
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert _has_buff(ctx, "건강")
        assert not _has_buff(ctx, "부상")

    def test_value_below(self):
        ctx = _make_context(
            _effect(
                condition_class_name="SelfHpValueBelowCondition", condition_value=50
            )
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert _has_buff(ctx, "부상")
        assert not _has_buff(ctx, "건강")

    def test_value_at_least(self):
        ctx = _make_context(
            _effect(
                condition_class_name="SelfHpValueAtLeastCondition", condition_value=50
            )
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.on_start_round()

        assert _has_buff(ctx, "건강")
        assert not _has_buff(ctx, "부상")
