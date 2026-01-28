from enum import Enum


class BuffDurationType(str, Enum):
    PASSIVE = "지속"
    TURN = "턴"
    COUNT = "회"


class BuffValueType(str, Enum):
    INTEGER = "정수"
    PERCENT = "퍼센트"
