import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.objects.define import (
    BattlefieldColumnIndex,
    CombatStatType,
    ValueSourceType,
)
from utils.dice import DiceRollResult, nd6

if TYPE_CHECKING:
    from battle.core.commands.models import CommandPartCalculator


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
    ) -> int | DiceRollResult:
        if self.value_source == ValueSourceType.FIXED and self.value is not None:
            return self.value

        elif (
            self.value_source == ValueSourceType.STAT_ATK_ROLL
            and calculator is not None
        ):
            result = nd6(
                calculator.context.milestone_n,
                calculator.buffed_stats_by_character[user_id][CombatStatType.ATK],
            )
            return result
        else:
            raise ValueError(self.value_source)


@dataclass
class ValueWithModifiers:
    base_value: BaseValueIndicator
    int_modifiers: list[IntValueModifier]
    float_modifiers: list[FloatValueModifier]

    roll_result: Optional[DiceRollResult] = None

    def __init__(
        self,
        base_value: BaseValueIndicator,
        modifiers: list[ValueModifierBase],
    ):
        self.base_value = base_value
        self.int_modifiers = []
        self.float_modifiers = []

        if (
            isinstance(self.base_value, BaseValueIndicator)
            and self.base_value.coefficient is not None
        ):
            self.float_modifiers.append(self.base_value.coefficient)

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
    ) -> int:
        if isinstance(self.base_value, int):
            base_value = self.base_value
        elif isinstance(self.base_value, BaseValueIndicator):
            base_value = self.base_value.get_value(user, target, calculator)
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

        total_float_modifier_value = sum(
            modifier.value for modifier in self.float_modifiers
        )
        value = math.floor(value * (1 + total_float_modifier_value))

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
        if self.float_modifiers:
            result_str += " * ("
            for modifier in self.float_modifiers:
                result_str += f"{'' if modifier.value < 0 else '+'}{math.floor(modifier.value * 100)}%[{modifier.source_name}]"
            result_str += ")"
        return result_str


@dataclass(frozen=True)
class MoveData:
    character_id: CharacterId
    to_position: BattlefieldColumnIndex


@dataclass(frozen=True)
class DamageData:
    attacker_id: CharacterId
    target_id: CharacterId
    value: BaseValueIndicator


@dataclass(frozen=True)
class HealData:
    healer_id: CharacterId
    target_id: CharacterId
    value: BaseValueIndicator
