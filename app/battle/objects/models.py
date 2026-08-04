import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from utils.dice import DiceRollResult, nd6

from battle.objects.define import (
    BattlefieldColumnIndex,
    CombatStatType,
    ValueSourceType,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class CharacterId:
    name: str

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)


@dataclass(frozen=True)
class BuffUid:
    given_by: CharacterId
    applied_to: CharacterId
    buff_name: str

    def __hash__(self):
        return hash((self.given_by, self.applied_to, self.buff_name))


@dataclass(frozen=True)
class ValueModifierBase:
    source_name: str
    # True면 FIXED(고정값) 대미지/힐에도 적용된다. 마력 적응(m_res)·희생 방어
    # 경감처럼 버프가 아닌 게임 메커니즘용. BuffGivenDamage/BuffReceivedDamage/
    # BuffGivenHeal 등 버프 유래 modifier는 기본값(False)을 그대로 써서
    # FIXED 값에는 영향을 주지 않는다.
    # kw_only: 서브클래스(IntValueModifier/FloatValueModifier)가 추가하는
    # 필수 필드 value가 기본값 있는 필드보다 뒤에 오게 되는 dataclass 순서
    # 제약을 피하기 위함.
    applies_to_fixed: bool = field(default=False, kw_only=True)


@dataclass(frozen=True)
class IntValueModifier(ValueModifierBase):
    value: int


@dataclass(frozen=True)
class FloatValueModifier(ValueModifierBase):
    value: float
    # "× (a × b)"처럼 여러 배율의 곱으로 분해해서 보여주고 싶을 때만 채운다.
    # (라벨, 퍼센트값) 쌍의 튜플. value는 이미 그 곱셈 결과이므로 실제 계산에는
    # 영향을 주지 않고 format_calculation()의 표시 방식만 바꾼다.
    display_factors: Optional[tuple[tuple[str, float], ...]] = None


@dataclass(frozen=True)
class BaseValueIndicator:
    value_source: ValueSourceType
    value: Optional[int] = None
    coefficient: Optional[FloatValueModifier] = None
    # CONSUMED_BUFF_STACK/REFERENCED_BUFF_STACK 전용: 대상 버프 id.
    # format_calculation()이 수치를 "{값}[{buff_id}]"로 라벨링하는 데 쓰인다
    # (계산식에서 어느 버프에서 온 수치인지 보여주기 위함). 다른 value_source에서는
    # 쓰이지 않는다.
    consumed_buff_id: Optional[str] = None

    def get_value(
        self,
        user_id: CharacterId,
        target_id: CharacterId,
        calculator: Optional["CommandPartCalculator"],
        effect_seq_number: int,
    ) -> int | DiceRollResult:
        if self.value_source == ValueSourceType.FIXED and self.value is not None:
            return self.value

        # calculator가 None인 경우는 AdminCommand 한정. AdminCommand는 고정 대미지만 사용한다.
        assert calculator is not None

        if self.value_source == ValueSourceType.STAT_ATK_ROLL:
            result = nd6(
                calculator.context.milestone_n,
                calculator.buffed_stats_by_character[user_id][CombatStatType.ATK],
            )
            return result

        elif self.value_source == ValueSourceType.STAT_ATK:
            return calculator.buffed_stats_by_character[user_id].total(
                CombatStatType.ATK
            )
        elif self.value_source == ValueSourceType.STAT_RANGE:
            return calculator.context.characters[user_id].status[CombatStatType.RANGE]
        elif self.value_source == ValueSourceType.STAT_MAX_HP:
            return calculator.context.characters[user_id].status[CombatStatType.MAX_HP]
        elif self.value_source == ValueSourceType.STAT_COST_PER_TURN:
            return calculator.context.characters[user_id].status[
                CombatStatType.COST_PER_TURN
            ]
        elif self.value_source == ValueSourceType.SELF_CURR_HP:
            return calculator.context.characters[user_id].status.curr_hp
        elif self.value_source == ValueSourceType.SELF_CURR_POSITION:
            return calculator.context.find_character_position(user_id).value
        elif self.value_source == ValueSourceType.TARGET_CURR_HP:
            return calculator.context.characters[target_id].status.curr_hp
        elif self.value_source == ValueSourceType.TARGET_CURR_POSITION:
            return calculator.context.find_character_position(target_id).value

        elif self.value_source == ValueSourceType.GIVEN_DAMAGE:
            # 현재 effect 포함, 이미 result_value가 설정된 damage 합산.
            # coefficient는 ValueWithModifiers.base_coefficient가 다른 값
            # 소스와 동일하게 적용한다 (계산식 표시를 위해 여기서 미리
            # 곱해두지 않는다).
            return sum(
                data.result_value
                for effect in calculator.data_by_effect[: effect_seq_number + 1]
                for data in effect.damage_data_list
                if data.result_value is not None
            )

        elif self.value_source == ValueSourceType.GIVEN_HEAL:
            # 현재 effect 포함, 이미 result_value가 설정된 heal 합산.
            # coefficient 처리는 GIVEN_DAMAGE와 동일.
            return sum(
                data.result_value
                for effect in calculator.data_by_effect[: effect_seq_number + 1]
                for data in effect.heal_data_list
                if data.result_value is not None
            )

        elif self.value_source == ValueSourceType.CONSUMED_BUFF_STACK:
            # 현재 effect 포함, 이미 result_value가 설정된 버프 제거량 합산.
            # coefficient 처리는 GIVEN_DAMAGE와 동일.
            return sum(
                data.result_value
                for effect in calculator.data_by_effect[: effect_seq_number + 1]
                for data in effect.buff_remove_data_list
                if data.result_value is not None
            )

        elif self.value_source == ValueSourceType.REFERENCED_BUFF_STACK:
            # CONSUMED_BUFF_STACK과 달리 스택을 소모하지 않고, target_id에게
            # 걸린 consumed_buff_id 버프의 "현재" 스택 수를 그대로 읽는다.
            assert self.consumed_buff_id is not None
            return calculator.context.get_buff_stack(target_id, self.consumed_buff_id)

        else:
            raise ValueError(self.value_source)


def _bucket_modifiers(
    modifiers: list[ValueModifierBase], is_fixed: bool
) -> tuple[list[IntValueModifier], list[FloatValueModifier]]:
    """0이 아닌 modifier를 int/float로 나눈다. is_fixed면 applies_to_fixed=False인
    (버프 유래) modifier는 걸러낸다."""
    int_modifiers: list[IntValueModifier] = []
    float_modifiers: list[FloatValueModifier] = []
    for modifier in modifiers:
        if is_fixed and not modifier.applies_to_fixed:
            continue
        if isinstance(modifier, IntValueModifier):
            if modifier.value != 0:
                int_modifiers.append(modifier)
        elif isinstance(modifier, FloatValueModifier):
            if modifier.value != 0:
                float_modifiers.append(modifier)
    return int_modifiers, float_modifiers


@dataclass
class ValueWithModifiers:
    # int는 실제 커맨드 파이프라인에서는 쓰이지 않고, calculator 없이 계수/
    # 그룹 계산만 검증하는 테스트에서 raw 값을 바로 넘기는 용도다(get_value()가
    # calculator를 참조하지 않고 그대로 반환하는 지름길을 탄다).
    base_value: int | BaseValueIndicator
    given_int_modifiers: list[IntValueModifier]
    given_float_modifiers: list[FloatValueModifier]
    received_int_modifiers: list[IntValueModifier]
    received_float_modifiers: list[FloatValueModifier]
    roll_result: Optional[DiceRollResult] = None
    base_display_value: Optional[int] = None

    base_coefficient: Optional[FloatValueModifier] = None

    def __init__(
        self,
        base_value: int | BaseValueIndicator,
        given_modifiers: list[ValueModifierBase],
        received_modifiers: list[ValueModifierBase],
    ):
        self.base_value = base_value
        self.roll_result = None
        self.base_display_value = None

        is_fixed = (
            isinstance(self.base_value, BaseValueIndicator)
            and self.base_value.value_source == ValueSourceType.FIXED
        )

        # 스킬 자체의 계수(백분율). 예: 230 → ×2.3. FIXED 값에는 적용하지 않는다
        # (버프성 배율과 동일 취급 — 실제로 FIXED와 coefficient가 같이 쓰이는
        # 곳은 현재 없다). GIVEN_DAMAGE/GIVEN_HEAL/CONSUMED_BUFF_STACK도 다른
        # 값 소스와 동일하게 여기서 계수를 적용해야 계산식에 표시된다
        # (예전에는 BaseValueIndicator.get_value() 안에서 미리 곱해 계산식에
        # 드러나지 않았다).
        self.base_coefficient = None
        if (
            not is_fixed
            and isinstance(self.base_value, BaseValueIndicator)
            and self.base_value.coefficient is not None
        ):
            self.base_coefficient = self.base_value.coefficient

        self.given_int_modifiers, self.given_float_modifiers = _bucket_modifiers(
            given_modifiers, is_fixed
        )
        self.received_int_modifiers, self.received_float_modifiers = _bucket_modifiers(
            received_modifiers, is_fixed
        )

    def get_value(
        self,
        calculator: Optional["CommandPartCalculator"],
        user: CharacterId,
        target: CharacterId,
        effect_seq_number: int,
    ) -> int:
        base_value: int | DiceRollResult
        if isinstance(self.base_value, int):
            base_value = self.base_value
        elif isinstance(self.base_value, BaseValueIndicator):
            base_value = self.base_value.get_value(
                user, target, calculator, effect_seq_number
            )
        else:
            raise TypeError(type(self.base_value))

        if isinstance(base_value, int):
            value = base_value
            self.base_display_value = base_value
        elif isinstance(base_value, DiceRollResult):
            self.roll_result = base_value
            value = base_value.result
        else:
            raise TypeError(type(base_value))

        total_int_modifier_value = sum(
            modifier.value
            for modifier in (*self.given_int_modifiers, *self.received_int_modifiers)
        )
        value += total_int_modifier_value

        if self.base_coefficient is not None:
            value = math.floor(value * self.base_coefficient.value / 100)

        # 주는 쪽/받는 쪽 퍼센트 그룹은 각각 독립적인 배율 (1 + Σ퍼센트/100)을
        # 이루고, 두 배율을 곱한다 (그룹 내부는 합연산, 그룹끼리는 곱연산).
        given_factor = max(
            0.0, 1 + sum(m.value for m in self.given_float_modifiers) / 100
        )
        received_factor = max(
            0.0, 1 + sum(m.value for m in self.received_float_modifiers) / 100
        )
        value = math.floor(value * given_factor * received_factor)

        return value

    def format_calculation(self) -> Optional[str]:
        """계산식 표시 문자열. 다이스도 안 굴리고 modifier/계수도 전혀 없으면
        (전형적으로 modifier가 없는 FIXED 값) 보여줄 게 없다는 뜻으로 None을
        반환한다."""
        has_content = (
            self.roll_result is not None
            or self.base_coefficient is not None
            or self.given_int_modifiers
            or self.given_float_modifiers
            or self.received_int_modifiers
            or self.received_float_modifiers
        )
        if not has_content:
            return None

        # CONSUMED_BUFF_STACK은 소모한 버프 이름을 숫자에 직접 라벨링해서 보여준다
        # (예: "5[유예된 재앙]") — 이 경우 배율에 다시 "[계수]"를 붙이면 중복이라 생략한다.
        consumed_buff_id = (
            self.base_value.consumed_buff_id
            if isinstance(self.base_value, BaseValueIndicator)
            else None
        )

        if self.roll_result is not None:
            result_str = str(self.roll_result)
        elif self.base_display_value is not None:
            if consumed_buff_id is not None:
                result_str = f"{self.base_display_value}[{consumed_buff_id}]"
            else:
                result_str = str(self.base_display_value)
        else:
            result_str = str(self.base_value)

        int_modifiers = [*self.given_int_modifiers, *self.received_int_modifiers]
        if int_modifiers:
            result_str += " + ("
            for modifier in int_modifiers:
                result_str += f"{'' if modifier.value < 0 else '+'}{modifier.value}[{modifier.source_name}]"
            result_str += ")"

        if self.base_coefficient is not None:
            if self.base_coefficient.display_factors is not None:
                factors_str = " × ".join(
                    f"{factor_value / 100:g}[{factor_label}]"
                    for factor_label, factor_value in self.base_coefficient.display_factors
                )
                result_str += f" × ({factors_str})"
            elif consumed_buff_id is not None:
                result_str += f" × {self.base_coefficient.value / 100:g}"
            else:
                result_str += (
                    f" × {self.base_coefficient.value / 100:g}"
                    f"[{self.base_coefficient.source_name}]"
                )

        for float_modifiers in (
            self.given_float_modifiers,
            self.received_float_modifiers,
        ):
            if not float_modifiers:
                continue
            group_str = "1"
            for float_modifier in float_modifiers:
                sign = "-" if float_modifier.value < 0 else "+"
                group_str += (
                    f" {sign} {abs(float_modifier.value) / 100:g}"
                    f"[{float_modifier.source_name}]"
                )
            result_str += f" × ({group_str})"

        return result_str


@dataclass(frozen=True)
class MoveData:
    character_id: CharacterId
    to_position: BattlefieldColumnIndex
    is_forced: bool = False


@dataclass(frozen=True)
class DamageData:
    attacker_id: CharacterId
    target_id: CharacterId
    value: BaseValueIndicator
    is_magic_attack: Optional[bool] = None
    # False면 "공격자가 대미지를 줄 때마다" 트리거되는 패시브(예:
    # BuffApplyDebuffOnDealingDamage)를 발동시키지 않는다. 버프 반격 등
    # 파생 대미지가 원래 패시브를 재귀적으로 유발하지 않도록 하는 용도.
    triggers_given_damage_passives: bool = True


@dataclass(frozen=True)
class HealData:
    healer_id: CharacterId
    target_id: CharacterId
    value: BaseValueIndicator
