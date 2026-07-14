import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from utils.dice import DiceRollResult, nd6

from battle.objects.define import (
    BattlefieldColumnIndex,
    CombatStatType,
    ValueSourceType,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import (
        CalculatorMutableData,
        CommandPartCalculator,
    )


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


@dataclass(frozen=True)
class IntValueModifier(ValueModifierBase):
    value: int


@dataclass(frozen=True)
class FloatValueModifier(ValueModifierBase):
    value: float


@dataclass(frozen=True)
class BaseValueIndicator:
    value_source: ValueSourceType
    value: Optional[int] = None
    coefficient: Optional[FloatValueModifier] = None

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
            # 현재 effect 포함, 이미 result_value가 설정된 damage 합산
            total = sum(
                data.result_value
                for effect in calculator.data_by_effect[: effect_seq_number + 1]
                for data in effect.damage_data_list
                if data.result_value is not None
            )
            if self.coefficient is not None:
                return math.floor(total * self.coefficient.value / 100)
            return total

        elif self.value_source == ValueSourceType.GIVEN_HEAL:
            # 현재 effect 포함, 이미 result_value가 설정된 heal 합산
            total = sum(
                data.result_value
                for effect in calculator.data_by_effect[: effect_seq_number + 1]
                for data in effect.heal_data_list
                if data.result_value is not None
            )
            if self.coefficient is not None:
                return math.floor(total * self.coefficient.value / 100)
            return total

        elif self.value_source == ValueSourceType.CONSUMED_BUFF_STACK:
            # 현재 effect 포함, 이미 result_value가 설정된 버프 제거량 합산
            total = sum(
                data.result_value
                for effect in calculator.data_by_effect[: effect_seq_number + 1]
                for data in effect.buff_remove_data_list
                if data.result_value is not None
            )
            if self.coefficient is not None:
                return math.floor(total * self.coefficient.value / 100)
            return total

        else:
            raise ValueError(self.value_source)


@dataclass
class ValueWithModifiers:
    base_value: BaseValueIndicator
    int_modifiers: list[IntValueModifier]
    float_modifiers: list[FloatValueModifier]
    roll_result: Optional[DiceRollResult] = None

    base_coefficient: Optional[FloatValueModifier] = None

    def __init__(
        self,
        base_value: BaseValueIndicator,
        modifiers: list[ValueModifierBase],
    ):
        self.base_value = base_value
        self.int_modifiers = []
        self.float_modifiers = []
        # 스킬 자체의 계수(백분율). 예: 230 → ×2.3. 없으면 기본 100%(×1.0).
        self.base_coefficient = None

        if (
            isinstance(self.base_value, BaseValueIndicator)
            and self.base_value.coefficient is not None
            and self.base_value.value_source
            not in (
                ValueSourceType.GIVEN_DAMAGE,
                ValueSourceType.GIVEN_HEAL,
                ValueSourceType.CONSUMED_BUFF_STACK,
            )
        ):
            self.base_coefficient = self.base_value.coefficient

        for modifier in modifiers:
            if isinstance(modifier, IntValueModifier):
                if modifier.value != 0:
                    self.int_modifiers.append(modifier)
            elif isinstance(modifier, FloatValueModifier):
                if modifier.value != 0:
                    self.float_modifiers.append(modifier)

    def get_value(
        self,
        calculator: Optional["CommandPartCalculator"],
        user: CharacterId,
        target: CharacterId,
        effect_seq_number: int,
    ) -> int:
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
        elif isinstance(base_value, DiceRollResult):
            self.roll_result = base_value
            value = base_value.result
        else:
            raise TypeError(type(base_value))

        total_int_modifier_value = sum(
            modifier.value for modifier in self.int_modifiers
        )
        value += total_int_modifier_value

        # 백분율 계수: 스킬 기본 계수(없으면 100%)에 버프 등 가감(퍼센트 포인트)을 더한다.
        # 예) 계수 230 + 버프 +20 → 250% → ×2.5. 음수로 0% 미만이 되면 0으로 클램프.
        coefficient_percent = (
            self.base_coefficient.value if self.base_coefficient is not None else 100
        )
        coefficient_percent += sum(
            modifier.value for modifier in self.float_modifiers
        )
        coefficient_percent = max(0, coefficient_percent)
        value = math.floor(value * coefficient_percent / 100)

        return value

    def __str__(self):
        result_str = ""
        if self.roll_result:
            result_str += str(self.roll_result)
        else:
            result_str += str(self.base_value)

        if self.int_modifiers:
            result_str += " + ("
            for modifier in self.int_modifiers:
                result_str += f"{'' if modifier.value < 0 else '+'}{modifier.value}[{modifier.source_name}]"
            result_str += ")"
        if self.base_coefficient is not None or self.float_modifiers:
            parts: list[str] = []
            if self.base_coefficient is not None:
                parts.append(
                    f"{math.floor(self.base_coefficient.value)}%[{self.base_coefficient.source_name}]"
                )
            for modifier in self.float_modifiers:
                parts.append(
                    f"{'' if modifier.value < 0 else '+'}{math.floor(modifier.value)}%[{modifier.source_name}]"
                )
            result_str += " * (" + " ".join(parts) + ")"
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


@dataclass(frozen=True)
class HealData:
    healer_id: CharacterId
    target_id: CharacterId
    value: BaseValueIndicator
