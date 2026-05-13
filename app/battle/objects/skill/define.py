from enum import Enum


class SkillValueType(str, Enum):
    INTEGER = "정수"
    PERCENT = "퍼센트"
    BUFF = "버프"
