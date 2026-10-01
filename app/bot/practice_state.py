from dataclasses import dataclass, field
from typing import Optional

from battle.objects.define import BattlefieldColumnIndex, CombatStatType
from battle.objects.models import CharacterId
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeBattleMode, PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager


@dataclass
class PracticeBattleState:
    """대련/상시전투/결투 세션 상태."""

    context: PracticeBattlefieldContext
    manager: PracticeRoundManager

    mode: PracticeBattleMode = PracticeBattleMode.PRACTICE

    round_n: int = 0
    # None이면 라운드 상한 없음(결투/상시전투) — 한쪽이 전멸할 때까지 계속된다.
    round_limit: Optional[int] = 3

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
    pending_participants: list[str] = field(default_factory=list)
    pending_placements: list[tuple] = field(default_factory=list)

    # 전투 시작 시점의 팀별 참가자 이름. 결투 패배 대가는 자진 기권해
    # 필드에서 빠진 캐릭터에게도 적용되므로, 현재 배치 상태가 아니라 시작
    # 시점의 명부를 봐야 한다.
    roster_by_side: dict[SideType, list[str]] = field(default_factory=dict)

    # 전투 시작 시점의 팀별 최대 체력 합. 승패는 체력 "비율"로
    # 가르는데, 필드에서 빠진 캐릭터(상시전투의 0 체력 적군, 자진 기권한
    # 참가자)는 context.characters에서 사라져 분모에서도 함께 빠진다 — 그러면
    # 잃은 인원이 많은 팀일수록 비율이 올라가는 역전이 생긴다. 시작 시점 값을
    # 붙잡아 두고 분모로 쓰면 "얼마나 잃었는가"가 그대로 비율에 남는다.
    initial_max_hp_by_side: dict[SideType, int] = field(default_factory=dict)

    # 상시전투 전용: 마지막으로 시트에 쓴 체력. 커맨드마다 바뀐 캐릭터만
    # 골라 써서 시트 쓰기 횟수를 줄인다.
    written_sheet_hp: dict[str, int] = field(default_factory=dict)

    @property
    def is_investigation(self) -> bool:
        return self.mode == PracticeBattleMode.INVESTIGATION

    def sheet_hp_changes(self) -> list[str]:
        """상시전투에서 마지막 시트 반영 이후 체력이 바뀐 캐릭터 이름(양 진영).

        직전 라운드 종료에 체력 0으로 필드에서 빠진 캐릭터도 포함한다 —
        라운드 종료 DoT로 쓰러지면 쓰러진 체력을 시트에 쓸 기회 없이 필드에서
        사라지기 때문이다."""
        if not self.mode.uses_sheet_hp:
            return []
        changed = [
            char.id.name
            for side in SideType
            for char in self.context.get_side_characters(side)
            if self.written_sheet_hp.get(char.id.name) != char.status.curr_hp
        ]
        changed += [
            char_id.name
            for char_id in self.manager.get_last_eliminated_characters()
            if char_id not in self.context.characters
            and self.written_sheet_hp.get(char_id.name) != 0
        ]
        return changed

    @property
    def is_duel_match(self) -> bool:
        """결투(임시 체력이 최대 체력이고, 패배 시 실제 체력이 깎이는 모드)."""
        return self.mode == PracticeBattleMode.DUEL

    @property
    def phase(self) -> Optional[PracticeRoundPhase]:
        return self.manager.phase

    def pending_actors(self) -> list[CharacterId]:
        return self.manager.pending_actors()

    def snapshot_initial_max_hp(self) -> None:
        """전투 시작(첫 라운드 진입) 시점에 팀별 최대 체력 합을 고정한다."""
        self.initial_max_hp_by_side = {
            side: self._live_max_hp_by_side(side) for side in SideType
        }

    def snapshot_roster(self) -> None:
        """전투 시작 시점에 팀별 참가자 명부를 고정한다."""
        self.roster_by_side = {
            side: [char.id.name for char in self.context.get_side_characters(side)]
            for side in SideType
        }

    def all_declared(self) -> bool:
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
        """승패 비율의 분자."""
        return sum(c.status.curr_hp for c in self.context.get_side_characters(side))

    def _live_max_hp_by_side(self, side: SideType) -> int:
        return sum(
            c.status[CombatStatType.MAX_HP]
            for c in self.context.get_side_characters(side)
        )

    def total_max_hp_by_side(self, side: SideType) -> int:
        """승패 비율의 분모. 스냅샷이 없으면(재기동 복원 등) 현재 필드
        기준으로 계산한다."""
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
