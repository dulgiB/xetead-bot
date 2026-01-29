from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.character.combat_stats import CombatStats
from battle.objects.define import (
    ActionType,
    CombatStatType,
    FactionType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillBaseData

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class CombatCharacter:
    def __init__(
        self,
        field: "BattlefieldContext",
        name: str,
        faction: FactionType,
        stats: CombatStats,
        *,
        passive_buff: BuffBase = None,
        skill_1: SkillBaseData = None,
        skill_2: SkillBaseData = None,
    ):
        self.field = field

        self.name: str = name  # serves as UID
        self.faction: FactionType = faction
        self.status: CombatStats = stats

        self.passive_buff: BuffBase | None = passive_buff

        self.skills: dict[ActionType, SkillBaseData | None] = {
            ActionType.SKILL_1: skill_1,
            ActionType.SKILL_2: skill_2,
        }

    def __str__(self):
        return (
            f"{self.name} ({self.status.curr_hp}/{self.status[CombatStatType.MAX_HP]})"
        )

    @property
    def id(self) -> CharacterId:
        return CharacterId(self.name)

    @property
    def foe_faction(self) -> FactionType:
        if self.faction == FactionType.ALLY:
            return FactionType.ENEMY
        elif self.faction == FactionType.ENEMY:
            return FactionType.ALLY

        raise ValueError(f"Unknown faction {self.faction}")
