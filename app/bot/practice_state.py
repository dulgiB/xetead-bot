from dataclasses import dataclass, field
from typing import Optional

from battle.objects.character.combat_character import CombatCharacter
from battle.objects.define import BattlefieldColumnIndex, CombatStatType
from battle.objects.models import CharacterId
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

    # 시트 기록용 영속 키. 라운드 시작 시점의 prep_post_id로 한 번 고정한다 —
    # prep_post_id 자체는 그 뒤 0으로 리셋되므로(선언 접수 종료 표시) 시트 키로
    # 재사용하면 재기동 이후 모든 기록이 field_id="0"으로 뒤섞인다.
    field_id: str = ""

    # 최초 [대련]/[상시전투] 개시 멘션의 visibility로 고정해, 세션 내내
    # 게시되는 퍼블릭 게시물이 이 값을 따르게 한다.
    visibility: str = "public"

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

    # 전투 시작 시점의 팀별 최대 체력 합(동료 제외). 승패는 체력 "비율"로
    # 가르는데, 필드에서 빠진 캐릭터(상시전투의 0 체력 적군, 자진 기권한
    # 참가자)는 context.characters에서 사라져 분모에서도 함께 빠진다 — 그러면
    # 잃은 인원이 많은 팀일수록 비율이 올라가는 역전이 생긴다. 시작 시점 값을
    # 붙잡아 두고 분모로 쓰면 "얼마나 잃었는가"가 그대로 비율에 남는다.
    initial_max_hp_by_side: dict[SideType, int] = field(default_factory=dict)

    @property
    def phase(self) -> Optional[PracticeRoundPhase]:
        return self.manager.phase

    def pending_actors(self) -> list[CharacterId]:
        """이번 페이즈에 아직 선언하지 않은 캐릭터 목록 (PracticeRoundManager 위임)."""
        return self.manager.pending_actors()

    def actable_characters(self, side: SideType) -> list[CombatCharacter]:
        """플레이어가 직접 조작하는 캐릭터만 (동료/소환수 제외).

        행동 선언 대기 판정, 차례 안내 명단, 승패용 체력 합계가 모두 이 기준을
        공유한다."""
        return [
            char
            for char in self.context.get_side_characters(side)
            if char.id not in self.context.companion_owners
        ]

    def snapshot_initial_max_hp(self) -> None:
        """전투 시작(첫 라운드 진입) 시점에 팀별 최대 체력 합을 고정한다."""
        self.initial_max_hp_by_side = {
            side: self._live_max_hp_by_side(side) for side in SideType
        }

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
        """팀의 현재 체력 합. 동료(소환수)는 제외한다 — 동료는 플레이어가
        조작하는 참가자가 아니라 소환자의 방어 장치이고, 전투 도중 소환·재소환
        되면서 팀의 체력 총량 자체를 바꾼다. 승패 비율의 분모
        (total_max_hp_by_side)는 전투 시작 시점 스냅샷이라, 동료를 분자에만
        더하면 비율이 100%를 넘고 동료를 잃은 팀은 반대로 손해를 본다."""
        return sum(c.status.curr_hp for c in self.actable_characters(side))

    def _live_max_hp_by_side(self, side: SideType) -> int:
        return sum(
            c.status[CombatStatType.MAX_HP] for c in self.actable_characters(side)
        )

    def total_max_hp_by_side(self, side: SideType) -> int:
        """승패 비율의 분모.

        전투 시작 시점 스냅샷과 현재 필드 합 중 큰 쪽을 쓴다 — 현재 필드 합만
        쓰면 필드에서 빠진 캐릭터가 분모에서도 함께 사라져 "잃은 인원이
        많을수록 비율이 올라가는" 역전이 생긴다. 스냅샷이 없으면(재기동 복원
        등) 현재 필드 기준으로 계산한다."""
        return max(
            self.initial_max_hp_by_side.get(side, 0), self._live_max_hp_by_side(side)
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
