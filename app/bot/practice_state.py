from dataclasses import dataclass, field
from typing import Optional

from battle.objects.define import BattlefieldColumnIndex
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager


@dataclass
class PracticeBattleState:
    """대련 또는 상시전투 세션 상태."""

    context: PracticeBattlefieldContext
    manager: PracticeRoundManager

    # 라운드 정보
    round_n: int = 0
    round_limit: int = 3

    # 게시물 ID
    prep_post_id: int = 0
    active_post_id: Optional[int] = None

    # 페이즈 (PracticeRoundManager에 위임)
    first_mover: Optional[SideType] = None
    second_mover: Optional[SideType] = None

    # 대련 전용: 참여 선언 추적
    expected_accts: list[str] = field(default_factory=list)
    declared: dict[str, tuple[SideType, BattlefieldColumnIndex]] = field(
        default_factory=dict
    )

    # 상시전투 전용 (admin이 준비)
    is_investigation: bool = False
    pending_participants: list[str] = field(default_factory=list)
    pending_placements: list[tuple] = field(default_factory=list)

    @property
    def phase(self) -> Optional[PracticeRoundPhase]:
        return self.manager.phase

    def all_declared(self) -> bool:
        """모든 expected_accts가 선언을 완료했는지 확인한다."""
        return bool(self.expected_accts) and all(
            a in self.declared for a in self.expected_accts
        )

    def teams_valid(self) -> bool:
        """양 팀에 최소 1명씩 있는지 확인한다."""
        sides = {side for side, _ in self.declared.values()}
        return SideType.SIDE_1 in sides and SideType.SIDE_2 in sides

    def start_round(self) -> None:
        self.round_n += 1
        self.manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
        self.first_mover = self.manager.first_mover
        self.second_mover = self.manager.second_mover

    def advance_to_second_mover(self) -> None:
        self.manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)

    def end_round(self) -> None:
        self.manager.end_round()

    def total_hp_by_side(self, side: SideType) -> int:
        return sum(
            c.status.curr_hp
            for c in self.context.get_side_characters(side)
        )

    def winner(self) -> Optional[SideType]:
        """남은 체력 기준으로 승자 SideType을 반환한다. 동점이면 None."""
        hp1 = self.total_hp_by_side(SideType.SIDE_1)
        hp2 = self.total_hp_by_side(SideType.SIDE_2)
        if hp1 > hp2:
            return SideType.SIDE_1
        if hp2 > hp1:
            return SideType.SIDE_2
        return None

    def side_label(self, side: Optional[SideType]) -> str:
        if self.is_investigation:
            if side == SideType.SIDE_1:
                return "아군"
            if side == SideType.SIDE_2:
                return "적군"
            return "알 수 없음"
        return side.value if side else "알 수 없음"
