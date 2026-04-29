import random
from dataclasses import dataclass, field


@dataclass
class DiceRollResult:
    bonus: int
    n_sides: int
    rolls: list[int] = field(default_factory=list)

    @property
    def result(self) -> int:
        return sum(self.rolls) + self.bonus


def nd6(n: int, bonus: int) -> DiceRollResult:
    res = DiceRollResult(n_sides=6, bonus=bonus)
    for i in range(n):
        res.rolls.append(random.randint(1, 6))
    return res
