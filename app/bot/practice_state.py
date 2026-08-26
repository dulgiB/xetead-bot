from dataclasses import dataclass, field
from typing import Optional

from battle.objects.define import BattlefieldColumnIndex, CombatStatType
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager


@dataclass
class PracticeBattleState:
    """대련 또는 상시전투 세션 상태."""

    context: PracticeBattlefieldContext
    manager: PracticeRoundManager

    round_n: int = 0
    round_limit: int = 3

    prep_post_id: int = 0
    active_post_id: Optional[int] = None

    # "필드"/"로그_전투" 시트에서 이 세션을 식별하는 영속 키. 라운드가
    # 시작되는 시점(_start_practice_battle/_start_investigation_battle)에
    # 그때의 prep_post_id로 한 번 고정된다 — prep_post_id 자체는 라운드
    # 시작 후 0으로 리셋되고(포지션 선언 접수 종료 표시) 재기동 복원 시에도
    # 항상 0이라, prep_post_id를 시트 키로 그대로 재사용하면 재기동 이후
    # 모든 기록이 field_id="0"으로 뒤섞인다 — 이 필드는 그 두 가지 역할을
    # 분리하기 위한 것이다.
    field_id: str = ""

    # 진행 게시물 visibility — 최초 [대련]/[상시전투] 개시 멘션의 visibility로
    # 고정해, 세션 내내 게시되는 퍼블릭 게시물들이 이 값을 그대로 따르게 한다.
    visibility: str = "public"

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
        return sum(c.status.curr_hp for c in self.context.get_side_characters(side))

    def total_max_hp_by_side(self, side: SideType) -> int:
        return sum(
            c.status[CombatStatType.MAX_HP]
            for c in self.context.get_side_characters(side)
        )

    def winner(self) -> Optional[SideType]:
        """체력 비율(현재 체력 합 / 최대 체력 합) 기준으로 승자 SideType을
        반환한다. 비율이 같으면 절대 체력 합으로 재비교하고, 그마저 같으면
        None(무승부)을 반환한다."""
        max1 = self.total_max_hp_by_side(SideType.SIDE_1)
        max2 = self.total_max_hp_by_side(SideType.SIDE_2)
        hp1 = self.total_hp_by_side(SideType.SIDE_1)
        hp2 = self.total_hp_by_side(SideType.SIDE_2)
        ratio1 = hp1 / max1 if max1 else 0
        ratio2 = hp2 / max2 if max2 else 0
        if ratio1 > ratio2:
            return SideType.SIDE_1
        if ratio2 > ratio1:
            return SideType.SIDE_2
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
