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



def nd6(n: int, bonus_list: list[Union[int, "IntValueModifier"]]) -> DiceRollResult:
    res = DiceRollResult(n_sides=6, bonus_list=bonus_list)
    for i in range(n):
        res.rolls.append(random.randint(1, 6))
    return res
