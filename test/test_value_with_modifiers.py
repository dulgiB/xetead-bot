"""ValueWithModifiers의 곱연산 그룹화(주는/받는 대미지)와 FIXED 값 면역
동작을 검증하는 단위 테스트. 커맨드 파이프라인 전체를 거치지 않고
ValueWithModifiers를 직접 구성해 계산/표시 로직만 좁혀서 확인한다.
"""

from battle.objects.define import ValueSourceType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    FloatValueModifier,
    IntValueModifier,
    ValueWithModifiers,
)
from utils.dice import DiceRollResult

_USER = CharacterId("시전자")
_TARGET = CharacterId("대상")


def test_given_and_received_groups_multiply_independently():
    """주는/받는 퍼센트 그룹은 각각 (1 + Σ%/100)을 이루고 서로 곱해져야 한다.

    base=100, given +30%, received -10% → floor(100 × 1.3 × 0.9) = 117.
    (구 합연산이었다면 floor(100 × 1.2) = 120이 나왔을 것 — 117과 달라야 한다.)
    """
    value = ValueWithModifiers(
        100,
        given_modifiers=[FloatValueModifier(source_name="주는 대미지 증가", value=30)],
        received_modifiers=[
            FloatValueModifier(source_name="받는 대미지 감소", value=-10)
        ],
    )
    assert value.get_value(None, _USER, _TARGET, 0) == 117


def test_base_coefficient_applies_as_its_own_multiplicative_factor():
    """스킬 자체 계수(150%)는 given/received 그룹과 별개의 곱셈 항이다.

    base=10, 계수 150% → floor(10 × 1.5) = 15, given +20% → floor(15 × 1.2) = 18.
    (raw int를 base_value로 넘겨 calculator 없이 계수/그룹 계산만 검증한다 —
    base_coefficient는 생성자가 아니라 테스트에서 직접 채운다.)
    """
    value = ValueWithModifiers(10, given_modifiers=[], received_modifiers=[])
    value.base_coefficient = FloatValueModifier(source_name="계수", value=150)
    value.given_float_modifiers = [
        FloatValueModifier(source_name="주는 대미지 증가", value=20)
    ]
    assert value.get_value(None, _USER, _TARGET, 0) == 18


def test_negative_group_factor_clamps_to_zero():
    """그룹 합산이 -100% 이하로 내려가도 대미지가 음수가 되지 않고 0으로 클램프."""
    value = ValueWithModifiers(
        100,
        given_modifiers=[],
        received_modifiers=[
            FloatValueModifier(source_name="받는 대미지 감소", value=-150)
        ],
    )
    assert value.get_value(None, _USER, _TARGET, 0) == 0


def test_fixed_value_ignores_buff_modifiers():
    """FIXED 대미지는 BuffGivenDamage/BuffReceivedDamage류(버프) 영향을 받지 않는다."""
    value = ValueWithModifiers(
        BaseValueIndicator(ValueSourceType.FIXED, 50),
        given_modifiers=[
            FloatValueModifier(source_name="주는 대미지 증가", value=50),
            IntValueModifier(source_name="주는 대미지 증가(정수)", value=10),
        ],
        received_modifiers=[
            FloatValueModifier(source_name="받는 대미지 감소", value=-30)
        ],
    )
    assert value.get_value(None, _USER, _TARGET, 0) == 50


def test_fixed_value_still_applies_non_buff_mechanics():
    """희생 방어 경감/마력 적응처럼 applies_to_fixed=True인 modifier는 FIXED에도 적용된다.

    (test_sacrifice_reduces_redirected_damage와 동일한 시나리오: 고정 50 대미지에
    희생 방어 20% 경감 → 40.)
    """
    value = ValueWithModifiers(
        BaseValueIndicator(ValueSourceType.FIXED, 50),
        given_modifiers=[],
        received_modifiers=[
            FloatValueModifier(
                source_name="희생 방어", value=-20, applies_to_fixed=True
            )
        ],
    )
    assert value.get_value(None, _USER, _TARGET, 0) == 40


def test_format_calculation_returns_none_for_plain_fixed_value():
    """modifier가 전혀 없는 FIXED 값은 보여줄 계산식이 없으므로 None."""
    value = ValueWithModifiers(
        BaseValueIndicator(ValueSourceType.FIXED, 50),
        given_modifiers=[],
        received_modifiers=[],
    )
    value.get_value(None, _USER, _TARGET, 0)
    assert value.format_calculation() is None


def test_format_calculation_shows_applied_mechanic_modifier_even_for_fixed():
    """FIXED라도 희생 방어처럼 실제로 적용된 modifier가 있으면 계산식을 보여준다."""
    value = ValueWithModifiers(
        BaseValueIndicator(ValueSourceType.FIXED, 50),
        given_modifiers=[],
        received_modifiers=[
            FloatValueModifier(
                source_name="희생 방어", value=-20, applies_to_fixed=True
            )
        ],
    )
    value.get_value(None, _USER, _TARGET, 0)
    assert value.format_calculation() == "50 × (1 - 0.2[희생 방어])"


def test_format_calculation_matches_given_received_group_example():
    """계수 + 주는/받는 그룹이 모두 있을 때 각 그룹이 괄호로 묶여 곱해진 형태로
    표시되어야 한다 (그룹 내부는 합연산, 그룹끼리는 곱연산)."""
    value = ValueWithModifiers(
        BaseValueIndicator(
            ValueSourceType.STAT_ATK,
            coefficient=FloatValueModifier(source_name="계수", value=120),
        ),
        given_modifiers=[
            FloatValueModifier(source_name="주는 대미지 증가", value=30),
            FloatValueModifier(source_name="주는 대미지 감소", value=-10),
        ],
        received_modifiers=[
            FloatValueModifier(source_name="받는 대미지 감소", value=-10),
            FloatValueModifier(
                source_name="마법 저항", value=15, applies_to_fixed=True
            ),
        ],
    )
    value.roll_result = DiceRollResult(bonus_list=[4], n_sides=6, rolls=[3])

    assert value.format_calculation() == (
        "(4 + 3[1d6]) × 1.2[계수] × (1 + 0.3[주는 대미지 증가] - 0.1[주는 대미지 감소])"
        " × (1 - 0.1[받는 대미지 감소] + 0.15[마법 저항])"
    )


def test_consumed_buff_stack_coefficient_shows_in_calculation():
    """GIVEN_DAMAGE/GIVEN_HEAL/CONSUMED_BUFF_STACK 소스도 다른 값 소스와 동일하게
    계수가 base_coefficient로 적용되어 계산식에 표시되어야 한다 (예전에는
    BaseValueIndicator.get_value() 내부에서 미리 곱해져 계산식에 드러나지
    않았다)."""
    context = _FakeConsumedStackCalculator(consumed_amount=2)
    value = ValueWithModifiers(
        BaseValueIndicator(
            ValueSourceType.CONSUMED_BUFF_STACK,
            coefficient=FloatValueModifier(source_name="계수", value=300),
        ),
        given_modifiers=[],
        received_modifiers=[],
    )
    result = value.get_value(context, _USER, _TARGET, 0)

    assert result == 6  # floor(2 × 3.0)
    assert value.format_calculation() == "2 × 3[계수]"


class _FakeConsumedStackCalculator:
    """CONSUMED_BUFF_STACK 값 소스가 참조하는 data_by_effect만 흉내내는 스텁."""

    def __init__(self, consumed_amount: int):
        from dataclasses import dataclass

        @dataclass
        class _RemoveCalc:
            result_value: int

        class _EffectData:
            def __init__(self, amount):
                self.buff_remove_data_list = [_RemoveCalc(result_value=amount)]

        self.data_by_effect = [_EffectData(consumed_amount)]
