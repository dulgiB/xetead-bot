from enum import Enum


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
        return str(self.value + 1)

    @classmethod
    def from_str(cls, input_str: str):
        if input_str == "1열" or input_str == "1":
            return BattlefieldColumnIndex.COL1
        elif input_str == "2열" or input_str == "2":
            return BattlefieldColumnIndex.COL2
        elif input_str == "3열" or input_str == "3":
            return BattlefieldColumnIndex.COL3
        elif input_str == "4열" or input_str == "4":
            return BattlefieldColumnIndex.COL4
        elif input_str == "5열" or input_str == "5":
            return BattlefieldColumnIndex.COL5
        elif input_str == "6열" or input_str == "6":
            return BattlefieldColumnIndex.COL6
        elif input_str == "7열" or input_str == "7":
            return BattlefieldColumnIndex.COL7
        else:
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

    STAT_ATK = "공격력 스탯"
    STAT_ATK_ROLL = "공격력 스탯 굴림"
    STAT_RANGE = "사거리 스탯"
    STAT_MAX_HP = "최대 체력 스탯"
    STAT_COST_PER_TURN = "턴당 코스트 스탯"

    SELF_CURR_HP = "자신의 현재 체력"
    SELF_CURR_POSITION = "자신의 현재 위치"
    TARGET_CURR_HP = "상대의 현재 체력"
    TARGET_CURR_POSITION = "상대의 현재 위치"

    GIVEN_DAMAGE = "해당 공격으로 입힌 대미지"


class ValueType(str, Enum):
    INTEGER = "정수"
    PERCENT = "퍼센트"


class MagicResistanceType(str, Enum):
    WEAK = "낮음"
    NORMAL = "보통"
    STRONG = "높음"


class ElementType(str, Enum):
    FATE = "숙명"
    RESIST = "저항"
    EXPLORE = "개척"
    CONNECT = "결속"


class BuffTargetType(str, Enum):
    DAMAGE = "대미지"
    HEAL = "회복"
    COST = "코스트"


class ActionType(str, Enum):
    ADMIN = "시스템 커맨드"
    MOVE = "이동"
    ATTACK = "공격"
    SKILL_1 = "스킬1"
    SKILL_2 = "스킬2"
    USE_ITEM = "아이템"


class BuffApplyTiming(str, Enum):
    ON_ROUND_START = "라운드 시작 시"
    ON_ACTION = "행동 시"
    ON_ROUND_END = "라운드 종료 시"
