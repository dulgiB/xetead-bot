from enum import Enum

# 결투가 끝나면 승패와 무관하게 참가자 전원이 그 결투에서 받은 임시 체력
# 피해의 이 백분율만큼 실제 체력("캐릭터" 시트의 체력)을 잃는다. 결투는 최대
# 체력 그대로 싸우므로, 전멸한 쪽은 최대 체력의 절반을 잃는다.
#
# 깎는 양은 내림한다 — 절반 계산을 `max_hp // 2`로 두는 다른 지점
# (PracticeBattleMode.uses_full_hp가 아닌 임시 체력 등)과 같은 기준이다.
DUEL_SETTLEMENT_DAMAGE_PERCENT = 50


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
    def uses_sheet_hp(self) -> bool:
        """임시 체력 없이 "캐릭터"/"에너미" 시트의 실제 체력으로 싸우고, 체력
        변동을 시트에 반영하는지. 상시전투는 상시조사 도중 실제로 벌어지는
        전투라 본 전투처럼 입은 피해가 남아야 한다."""
        return self == PracticeBattleMode.INVESTIGATION

    @property
    def stakes_sheet_hp(self) -> bool:
        """전투 결과가 시트의 실제 체력에 남는지. 대련만 아무것도 남기지 않는
        연습이다."""
        return self != PracticeBattleMode.PRACTICE

    @property
    def has_round_limit(self) -> bool:
        """라운드 상한이 있는지. 결투와 상시전투는 한쪽이 전멸할 때까지
        계속된다."""
        return self == PracticeBattleMode.PRACTICE


class PracticeRoundPhase(Enum):
    FIRST_MOVER_ACTION = "선공 행동"
    SECOND_MOVER_ACTION = "후공 행동"
