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
class DailyQuestPools:
    """'일일 의뢰' 시트에서 읽어온 세 값 풀.

    client_category/client_name/quest_content는 각 컬럼 쌍(`xxx`,
    `xxx_active`)이 사실상 독립된 테이블이라 행 단위로 서로 대응하지
    않는다 — 조립 시 각 풀에서 따로 하나씩 뽑는다.
    """

    client_categories: list[str]
    client_names: list[
        str
    ]  # "로부터"/"으로부터" 조사까지 포함해서 입력 (예: "노인으로부터")
    quest_contents: list[str]


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
