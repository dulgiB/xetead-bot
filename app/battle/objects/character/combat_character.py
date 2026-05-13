from typing import TYPE_CHECKING

from battle.objects.character.combat_stats import CombatStats
from battle.objects.define import CombatStatType, FactionType
from battle.objects.models import CharacterId
from battle.objects.skill.models import Skill

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class CombatCharacter:
    def __init__(
        self,
        context: "BattlefieldContext",
        char_id: CharacterId,
        faction: FactionType,
        stats: CombatStats,
        *,
        skills: list[Skill],
    ):
        self.field = context
        self.id = char_id

        self.faction: FactionType = faction
        self.status: CombatStats = stats
        self.skills = skills

    def __str__(self):
        return f"{self.id} ({self.status.curr_hp}/{self.status[CombatStatType.MAX_HP]})"

    @property
    def foe_faction(self) -> FactionType:
        if self.faction == FactionType.ALLY:
            return FactionType.ENEMY
        elif self.faction == FactionType.ENEMY:
            return FactionType.ALLY

        raise ValueError(f"Unknown faction {self.faction}")
