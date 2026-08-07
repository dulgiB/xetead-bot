from dataclasses import dataclass
from enum import Enum


class DailyQuestSuccessType(str, Enum):
    GREAT_SUCCESS = "대성공"
    SUCCESS = "성공"
    CLOSE_SUCCESS = "아슬아슬한 성공"


@dataclass(frozen=True)
class DailyQuestResultMessageData:
    success_type: DailyQuestSuccessType
    message: str

    @classmethod
    def from_dict(cls, raw: dict) -> "DailyQuestResultMessageData":
        return cls(
            success_type=DailyQuestSuccessType(raw["success_type"]),
            message=str(raw["message"]),
        )


@dataclass(frozen=True)
class DailyQuestData:
    id: str
    client_name: str
    description: str
    location: str  # 빈 문자열이면 위치 무관

    @classmethod
    def from_dict(cls, raw: dict) -> "DailyQuestData":
        return cls(
            id=raw["id"],
            client_name=raw["client_name"],
            description=raw["description"],
            location=str(raw.get("location", "") or ""),
        )


@dataclass(frozen=True)
class QuestData:
    id: str
    name: str
    description: str
    type: str  # 운반 / 탐사 / 전투
    subtype: str  # 상시 / 일반
    location: str
    venue_name: str
    reward: str
    available_until: str

    @classmethod
    def from_dict(cls, raw: dict) -> "QuestData":
        return cls(
            id=raw["id"],
            name=raw["name"],
            description=raw["description"],
            type=raw.get("type", ""),
            subtype=raw.get("subtype", ""),
            location=str(raw.get("location", "") or ""),
            venue_name=str(raw.get("venue_name", "") or ""),
            reward=str(raw.get("reward", "") or ""),
            available_until=str(raw.get("available_until", "") or ""),
        )
