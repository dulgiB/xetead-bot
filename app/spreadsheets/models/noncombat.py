from dataclasses import dataclass
from enum import Enum


class NoncombatStatType(str, Enum):
    PHYSICAL = "육체"
    KNOWLEDGE = "지식"
    HUMAN = "인간"
    MAGIC = "마법"
    TECHNOLOGY = "기술"


NON_COMBAT_STATS: list[str] = [e.value for e in NoncombatStatType]


@dataclass(frozen=True)
class NoncombatCharacterDataFromSpreadsheet:
    # 비전투 스탯 (0–5)
    stat_physical: int = 0
    stat_knowledge: int = 0
    stat_human: int = 0
    stat_magic: int = 0
    stat_technology: int = 0
    # 재화
    gold: int = 0
    daily_quest_date: str = ""  # YYYY-MM-DD, 미수행이면 ""

    @classmethod
    def from_dict(cls, raw: dict[str, str | int | bool]):
        return cls(
            stat_physical=int(raw.get("stat_physical", 0) or 0),
            stat_knowledge=int(raw.get("stat_knowledge", 0) or 0),
            stat_human=int(raw.get("stat_human", 0) or 0),
            stat_magic=int(raw.get("stat_magic", 0) or 0),
            stat_technology=int(raw.get("stat_technology", 0) or 0),
            gold=int(raw.get("gold", 0) or 0),
            daily_quest_date=str(raw.get("daily_quest_date", "") or ""),
        )

    def get_noncombat_stat(self, stat_type: NoncombatStatType) -> int:
        return getattr(self, f"stat_{stat_type.name.lower()}")
