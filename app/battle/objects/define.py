from enum import Enum

CHARACTER_PER_COLUMN = 3


class BattlefieldColumnIndex(Enum):
    NONE = 7

    COL1 = 0
    COL2 = 1
    COL3 = 2
    COL4 = 3
    COL5 = 4
    COL6 = 5
    COL7 = 6

    def __str__(self):
        if self.value == 7:
            return "-"
        return str(self.value + 1)

    @classmethod
    def from_str(cls, input_str: str):
        mapping: dict[str, "BattlefieldColumnIndex"] = {
            "1열": cls.COL1, "1": cls.COL1,
            "2열": cls.COL2, "2": cls.COL2,
            "3열": cls.COL3, "3": cls.COL3,
            "4열": cls.COL4, "4": cls.COL4,
            "5열": cls.COL5, "5": cls.COL5,
            "6열": cls.COL6, "6": cls.COL6,
            "7열": cls.COL7, "7": cls.COL7,
        }
        if input_str in mapping:
            return mapping[input_str]
        raise ValueError(input_str)


class FactionType(str, Enum):
    ALLY = "아군"
    ENEMY = "적군"


class CombatStatType(str, Enum):
    ATK = "공격력"
    RANGE = "사거리"
    MAX_HP = "최대 체력"
    COST_PER_TURN = "턴당 코스트"


class ValueSourceType(str, Enum):
    FIXED = "고정값"

    STAT_ATK = "공격력"
    STAT_ATK_ROLL = "공격 굴림값"
    STAT_RANGE = "사거리"
    STAT_MAX_HP = "최대 체력"
    STAT_COST_PER_TURN = "턴당 코스트"

    SELF_CURR_HP = "자신의 현재 체력"
    SELF_CURR_POSITION = "자신의 현재 위치"
    TARGET_CURR_HP = "상대의 현재 체력"
    TARGET_CURR_POSITION = "상대의 현재 위치"

class ValueType(str, Enum):
    INTEGER = "정수"
    PERCENT = "퍼센트"


class MagicResistanceType(str, Enum):
    WEAK = "낮음"
    NORMAL = "보통"
    STRONG = "높음"


class BuffTargetType(str, Enum):
    DAMAGE = "대미지"
    HEAL = "회복"
    COST = "코스트"


class ActionType(str, Enum):
    ADMIN = "시스템 커맨드"
    MOVE = "이동"
    ATTACK = "공격"
    SKILL = "스킬"
    USE_ITEM = "아이템"


class BuffApplyTiming(str, Enum):
    ON_ROUND_START = "라운드 시작 시"
    ON_ACTION = "행동 시"
    ON_ROUND_END = "라운드 종료 시"


class BuffCountDeductCondition(str, Enum):
    ON_ATTACK = "공격 시"
    ON_HIT = "피격 시"
