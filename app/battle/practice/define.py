from enum import Enum


class SideType(str, Enum):
    SIDE_1 = "1팀"
    SIDE_2 = "2팀"

    @property
    def opposite(self) -> "SideType":
        return SideType.SIDE_2 if self == SideType.SIDE_1 else SideType.SIDE_1


class PracticeRoundPhase(Enum):
    FIRST_MOVER_ACTION = "선공 행동"
    SECOND_MOVER_ACTION = "후공 행동"
