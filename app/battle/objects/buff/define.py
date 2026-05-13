from enum import Enum


class BuffDurationType(str, Enum):
    PASSIVE = "지속"
    TURN = "턴"
    COUNT = "회"
