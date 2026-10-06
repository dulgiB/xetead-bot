from datetime import date
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
        fate_date: str = "",
        span: int = 1,
    ):
        self.field = context
        self.id = char_id

        self.faction: FactionType = faction
        self.status: CombatStats = stats
        self.skills = skills
        # 공개 노출 지점(필드 시트/전투 답글)에서 체력을 "?/?"로 가린다.
        self.hide_hp = hide_hp
        # 마지막으로 운명간섭을 쓴 날짜(YYYY-MM-DD, 미사용이면 ""). 실제 사용 시
        # 여기가 먼저 갱신되고, 봇 계층이 뒤이어 시트에 같은 날짜를 기록한다.
        self.fate_date = fate_date
        # 전장에서 차지하는 열 수. find_character_position()은 그중 가장 왼쪽
        # 열을 가리키고, 점유 열 전체는 find_character_columns()가 돌려준다.
        self.span = max(1, span)

    def __str__(self):
        return f"{self.id} ({self.status.curr_hp}/{self.status[CombatStatType.MAX_HP]})"

    @property
    def fate_used(self) -> bool:
        """오늘 이미 운명간섭을 썼는지. 판정할 때마다 오늘 날짜와 비교하므로
        결투/상시전투처럼 며칠 이어지는 전투에서도 자정에 제한이 풀린다."""
        return bool(self.fate_date) and self.fate_date == date.today().isoformat()

    @property
    def foe_faction(self) -> FactionType:
        if self.faction == FactionType.ALLY:
            return FactionType.ENEMY
        elif self.faction == FactionType.ENEMY:
            return FactionType.ALLY

        raise ValueError(f"Unknown faction {self.faction}")
