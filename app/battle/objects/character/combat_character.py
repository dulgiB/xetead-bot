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
        hide_hp: bool = False,
        fate_used: bool = False,
    ):
        self.field = context
        self.id = char_id

        self.faction: FactionType = faction
        self.status: CombatStats = stats
        self.skills = skills
        # 공개 노출 지점(필드 시트/전투 답글)에서 체력을 "?/?"로 가린다.
        self.hide_hp = hide_hp
        # 배치 시점 날짜와 시트의 fate_date를 비교한 결과. 실제 사용 시 여기가
        # 먼저 True가 되고, 봇 계층이 뒤이어 시트에 날짜를 기록한다.
        self.fate_used = fate_used

    def __str__(self):
        return f"{self.id} ({self.status.curr_hp}/{self.status[CombatStatType.MAX_HP]})"

    @property
    def foe_faction(self) -> FactionType:
        if self.faction == FactionType.ALLY:
            return FactionType.ENEMY
        elif self.faction == FactionType.ENEMY:
            return FactionType.ALLY

        raise ValueError(f"Unknown faction {self.faction}")
