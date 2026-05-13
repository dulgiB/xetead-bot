from typing import TYPE_CHECKING, Optional

from battle.objects.character.combat_stats import CombatStats
from battle.objects.define import (
    ActionType,
    CombatStatType,
    ElementType,
    FactionType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.models import Skill, SkillData

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class CombatCharacter:
    def __init__(
        self,
        context: "BattlefieldContext",
        char_id: CharacterId,
        element: ElementType,
        faction: FactionType,
        stats: CombatStats,
        *,
        skill_1: Optional[Skill],
        skill_2: Optional[Skill],
    ):
        self.field = context
        self.id = char_id
        self.element = element

        self.faction: FactionType = faction
        self.status: CombatStats = stats

        self.skills: dict[ActionType, Optional[Skill]] = {
            ActionType.SKILL_1: skill_1,
            ActionType.SKILL_2: skill_2,
        }

    def __str__(self):
        return f"{self.id} ({self.status.curr_hp}/{self.status[CombatStatType.MAX_HP]})"

    @property
    def foe_faction(self) -> FactionType:
        if self.faction == FactionType.ALLY:
            return FactionType.ENEMY
        elif self.faction == FactionType.ENEMY:
            return FactionType.ALLY

        raise ValueError(f"Unknown faction {self.faction}")
