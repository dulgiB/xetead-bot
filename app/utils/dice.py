import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from battle.objects.models import IntValueModifier


@dataclass
class DiceRollResult:
    bonus_list: list[Union[int, "IntValueModifier"]]
    n_sides: int
    rolls: list[int] = field(default_factory=list)

    @property
    def result(self) -> int:
        bonus_value = 0
        for bonus in self.bonus_list:
            if isinstance(bonus, int):
                bonus_value += bonus
            else:
                bonus_value += bonus.value

        return sum(self.rolls) + bonus_value

    def __str__(self):
        result_str = "("
        if len(self.bonus_list) == 1:
            result_str += str(self.bonus_list[0])
        else:
            result_str += "("
            for bonus in self.bonus_list:
                if isinstance(bonus, int):
                    result_str += str(bonus)
                else:
                    result_str += f" + {bonus.value}[{bonus.source_name}]"
            result_str += ")"

        result_str += " + "
        result_str += " + ".join(str(roll) for roll in self.rolls)
        result_str += ")"
        return result_str


def nd6(n: int, bonus_list: list[Union[int, "IntValueModifier"]]) -> DiceRollResult:
    res = DiceRollResult(n_sides=6, bonus_list=bonus_list)
    for i in range(n):
        res.rolls.append(random.randint(1, 6))
    return res
