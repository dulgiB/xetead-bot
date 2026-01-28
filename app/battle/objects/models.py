import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.objects.define import CombatStatType, ValueSourceType
from utils.dice import DiceRollResult, nd6

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class CharacterId:
    name: str

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)


@dataclass(frozen=True)
class BuffId:
    given_by: CharacterId
    applied_to: CharacterId
    buff_name: str

    def __hash__(self):
        return hash((self.given_by, self.applied_to, self.buff_name))


@dataclass(frozen=True)
class IntValueModifier:
    value: int


@dataclass(frozen=True)
class FloatValueModifier:
    value: float


@dataclass(frozen=True)
class BaseValueIndicator:
    value_source: ValueSourceType
    coefficient: Optional[FloatValueModifier] = None

    def get_value(
        self, context: "BattlefieldContext", user: CharacterId, target: CharacterId
    ) -> int | DiceRollResult:
        if self.value_source == ValueSourceType.STAT_ATK_ROLL:
            return nd6(context.characters[user].status[CombatStatType.ATK])
        else:
            raise ValueError(self.value_source)


@dataclass
class ValueWithModifiers:
    base_value: int | BaseValueIndicator
    int_modifiers: list[IntValueModifier]
    float_modifiers: list[FloatValueModifier]

    roll_result: Optional[DiceRollResult] = None

    def __init__(
        self,
        base_value: int | BaseValueIndicator,
        modifiers: list[IntValueModifier | FloatValueModifier],
    ):
        self.base_value = base_value
        self.int_modifiers = [
            modifier for modifier in modifiers if isinstance(modifier, IntValueModifier)
        ]
        self.float_modifiers = [
            modifier
            for modifier in modifiers
            if isinstance(modifier, FloatValueModifier)
        ]

    def get_value(
        self, context: "BattlefieldContext", user: CharacterId, target: CharacterId
    ) -> int:
        if isinstance(self.base_value, int):
            base_value = self.base_value
        elif isinstance(self.base_value, BaseValueIndicator):
            base_value = self.base_value.get_value(context, user, target)
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
        if isinstance(self.base_value, int):
            pass

        elif isinstance(self.base_value, DiceRollResult):
            pass

        raise TypeError(type(self.base_value))
