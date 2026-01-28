from dataclasses import dataclass

from battle.objects.character.combat_stats import CombatStats
from battle.objects.define import CombatStatType
from battle.objects.models import (
    FloatValueModifier,
    IntValueModifier,
    ValueWithModifiers,
)


@dataclass(frozen=True)
class BuffedStats:
    base_stats: CombatStats
    stat_bonuses: dict[CombatStatType, list[IntValueModifier | FloatValueModifier]]

    def __getitem__(self, stat_type: CombatStatType) -> ValueWithModifiers:
        return ValueWithModifiers(
            self.base_stats[stat_type], self.stat_bonuses[stat_type]
        )
