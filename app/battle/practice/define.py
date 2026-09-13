from enum import Enum


class SideType(str, Enum):
    SIDE_1 = "1팀"
    SIDE_2 = "2팀"

    @property
    def opposite(self) -> "SideType":
        return SideType.SIDE_2 if self == SideType.SIDE_1 else SideType.SIDE_1


class PracticeBattleMode(str, Enum):
    """축소 라운드 관리(PracticeRoundManager)를 공유하는 전투 종류.

    값은 그대로 게시물 라벨("◊ 대련 시작" 등)로 쓰인다.
    """

    PRACTICE = "대련"
    INVESTIGATION = "상시전투"


class PracticeRoundPhase(Enum):
    FIRST_MOVER_ACTION = "선공 행동"
    SECOND_MOVER_ACTION = "후공 행동"
