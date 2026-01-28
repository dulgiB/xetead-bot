import random
from dataclasses import dataclass, field


@dataclass
class DiceRollResult:
    n_sides: int
    rolls: list[int] = field(default_factory=list)

    @property
    def result(self) -> int:
        return sum(self.rolls)


def nd6(n: int) -> DiceRollResult:
    res = DiceRollResult(n_sides=6)
    for i in range(n):
        res.rolls.append(random.randint(1, 6))
    return res

