from dataclasses import dataclass
from enum import Enum

from utils.spreadsheet_bool import parse_spreadsheet_bool


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
class QuestLocationData:
    """'일반 의뢰' 시트에서 장소 자체를 나타내는 행.

    `id`가 장소 이름이고 `name`이 비어 있는 행이 장소 행이다. 그 장소에
    속한 의뢰 행들의 `id`는 `{장소 이름}_{의뢰 type}`로 고정된다
    (`load_general_quest_sheet` 참고). 장소 행에는 수주 상태 개념이 없어
    `description_normal`은 쓰지 않고 `description_quest`만 읽는다.
    """

    id: str
    active: bool
    description_quest: str

    @classmethod
    def from_dict(cls, raw: dict) -> "QuestLocationData":
        return cls(
            id=str(raw["id"]),
            active=parse_spreadsheet_bool(raw.get("active", False)),
            description_quest=str(raw.get("description_quest", "") or ""),
        )


@dataclass(frozen=True)
class QuestData:
    """'일반 의뢰' 시트에서 실제 의뢰를 나타내는 행 (`id` = `{장소 이름}_{type}`)."""

    id: str
    active: bool
    location: str  # 세부 장소 표시 이름 (예: 광장/상점가/항구)
    name: str
    description_quest: str  # 미수주 상태에서 노출할 설명
    description_normal: str  # 수주된 이후 노출할 설명
    type: str  # 운반 / 탐사 / 전투
    subtype: str  # 상시 / 일반
    reward: str
    available_until: str
    taken_by: str  # 이 의뢰를 수주한 캐릭터 acct들을 쉼표로 이어붙인 문자열 (없으면 "")

    @classmethod
    def from_dict(cls, raw: dict) -> "QuestData":
        return cls(
            id=str(raw["id"]),
            active=parse_spreadsheet_bool(raw.get("active", False)),
            location=str(raw.get("location", "") or ""),
            name=str(raw.get("name", "") or ""),
            description_quest=str(raw.get("description_quest", "") or ""),
            description_normal=str(raw.get("description_normal", "") or ""),
            type=str(raw.get("type", "") or ""),
            subtype=str(raw.get("subtype", "") or ""),
            reward=str(raw.get("reward", "") or ""),
            available_until=str(raw.get("available_until", "") or ""),
            taken_by=str(raw.get("taken_by", "") or ""),
        )

    def taken_by_list(self) -> list[str]:
        return [a.strip() for a in self.taken_by.split(",") if a.strip()]

    def current_description(self) -> str:
        return self.description_normal if self.taken_by_list() else self.description_quest
