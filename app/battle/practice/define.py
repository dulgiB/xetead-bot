from enum import Enum


class SideType(str, Enum):
    SIDE_1 = "1팀"
    SIDE_2 = "2팀"

    @property
    def opposite(self) -> "SideType":
        return SideType.SIDE_2 if self == SideType.SIDE_1 else SideType.SIDE_1


class PracticeBattleMode(str, Enum):
    """축소 라운드 관리(PracticeRoundManager)를 공유하는 전투 종류.

    값은 그대로 게시물 라벨("◊ 결투 시작" 등)로 쓰인다.
    """

    PRACTICE = "대련"
    INVESTIGATION = "상시전투"
    DUEL = "결투"

    @property
    def uses_full_hp(self) -> bool:
        """임시 체력을 최대 체력 그대로 쓰는지(False면 절반)."""
        return self == PracticeBattleMode.DUEL

    @property
    def has_round_limit(self) -> bool:
        """라운드 상한이 있는지. 결투는 한쪽이 전멸할 때까지 계속된다."""
        return self != PracticeBattleMode.DUEL


class PracticeRoundPhase(Enum):
    FIRST_MOVER_ACTION = "선공 행동"
    SECOND_MOVER_ACTION = "후공 행동"
