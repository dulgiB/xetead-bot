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
    name: str = ""
    # 비전투 스탯 (0–5)
    stat_physical: int = 0
    stat_knowledge: int = 0
    stat_human: int = 0
    stat_magic: int = 0
    stat_technology: int = 0
    # 재화
    gold: int = 0
    daily_quest_date: str = ""  # YYYY-MM-DD, 미수행이면 ""
    # 봇이 판정 답글을 기다리는 게시물 ID(진행 중이 아니면 ""). 재기동으로
    # 인메모리 상태가 사라져도 이 컬럼으로 복원할 수 있게 한다.
    daily_quest_status_id: str = ""
    # 전투용 캐릭터 시트의 curr_hp/max_hp 컬럼을 그대로 공유한다.
    curr_hp: int = 0
    max_hp: int = 0
    # 전투용 캐릭터 시트와 공유. [판정+/스탯]이 "부활 1회 이상 & 오늘 미사용"을
    # 확인하는 데 쓴다.
    revival_count: int = 0
    fate_date: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, str | int | bool]):
        return cls(
            name=str(raw.get("name", "") or ""),
            stat_physical=int(raw.get("stat_physical", 0) or 0),
            stat_knowledge=int(raw.get("stat_knowledge", 0) or 0),
            stat_human=int(raw.get("stat_human", 0) or 0),
            stat_magic=int(raw.get("stat_magic", 0) or 0),
            stat_technology=int(raw.get("stat_technology", 0) or 0),
            gold=int(raw.get("gold", 0) or 0),
            daily_quest_date=str(raw.get("daily_quest_date", "") or ""),
            daily_quest_status_id=str(raw.get("daily_quest_status_id", "") or ""),
            curr_hp=int(raw.get("curr_hp", 0) or 0),
            max_hp=int(raw.get("max_hp", 0) or 0),
            revival_count=int(raw.get("revival_count", 0) or 0),
            fate_date=str(raw.get("fate_date", "") or ""),
        )

    def get_noncombat_stat(self, stat_type: NoncombatStatType) -> int:
        return getattr(self, f"stat_{stat_type.name.lower()}")
