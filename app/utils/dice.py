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
        result_str += f"{sum(self.rolls)}[{len(self.rolls)}d{self.n_sides}]"
        result_str += ")"
        return result_str


def nd6(
    n: int,
    bonus_list: list[Union[int, "IntValueModifier"]],
    always_max: bool = False,
) -> DiceRollResult:
    """always_max면 굴리지 않고 모든 주사위를 6으로 둔다(굴림값이 항상
    최대치인 패시브용). 표시는 일반 굴림과 같다."""
    res = DiceRollResult(n_sides=6, bonus_list=bonus_list)
    for i in range(n):
        res.rolls.append(6 if always_max else random.randint(1, 6))
    return res
