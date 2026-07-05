from dataclasses import dataclass

from battle.objects.character.combat_stats import CombatStats
from battle.objects.define import CombatStatType
from battle.objects.models import IntValueModifier


@dataclass(frozen=True)
class BuffedStats:
    base_stats: CombatStats

    # 스탯 보너스는 무조건 정수 값만
    stat_bonuses: dict[CombatStatType, list[IntValueModifier]]

    def __getitem__(self, stat_type: CombatStatType) -> list[int | IntValueModifier]:
        return [self.base_stats[stat_type]] + self.stat_bonuses[stat_type]

    def total(self, stat_type: CombatStatType) -> int:
        return sum(
            value if isinstance(value, int) else value.value
            for value in self[stat_type]
        )
