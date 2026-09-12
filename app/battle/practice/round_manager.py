import random

from battle.core.command_processors import process_ally_command
from battle.core.commands.models import CharacterCommand, CommandProcessResult
from battle.exceptions import CommandValidationError
from battle.objects.models import CharacterId
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType


class PracticeRoundManager:
    """
    대련 턴 진행 관리자.

    턴 흐름:
      to_phase(FIRST_MOVER_ACTION)  — 라운드 시작 + 선공/후공 결정
      process_command(...) × N       — 선공 측 캐릭터 전원이 각자 1회 선언
      to_phase(SECOND_MOVER_ACTION) — 후공 페이즈로 전환
      process_command(...) × N       — 후공 측 캐릭터 전원이 각자 1회 선언
      end_round()                    — 라운드 종료 버프 처리 후 다음 턴 대기

    페이즈를 언제 넘길지는 호출측이 pending_actors()를 보고 정한다.
    """

    def __init__(self, context: PracticeBattlefieldContext) -> None:
        self._context = context
        self._phase: PracticeRoundPhase | None = None
        self._first_mover: SideType | None = None
        self._second_mover: SideType | None = None
        self._declared_this_phase: set[CharacterId] = set()

    @property
    def first_mover(self) -> SideType | None:
        return self._first_mover

    @property
    def second_mover(self) -> SideType | None:
        return self._second_mover

    @property
    def phase(self) -> PracticeRoundPhase | None:
        return self._phase

    @property
    def declared_this_phase(self) -> set[CharacterId]:
        return self._declared_this_phase

    def set_phase_for_restore(
        self,
        phase: PracticeRoundPhase,
        first_mover: SideType | None,
        second_mover: SideType | None,
        declared: "set[CharacterId] | None" = None,
    ) -> None:
        """봇 재기동 복원 전용. 크래시 이전 값을 그대로 이어받아야 하므로
        (다시 정하면 실제 진행과 어긋난다) 호출측이 명시적으로 넘긴다.
        `declared`를 빠뜨리면 이미 행동한 캐릭터가 같은 페이즈에 한 번 더
        행동할 수 있게 된다."""
        self._phase = phase
        self._first_mover = first_mover
        self._second_mover = second_mover
        self._declared_this_phase = set(declared or ())

    def expected_side(self) -> SideType | None:
        """지금 행동할 차례인 팀."""
        if self._phase == PracticeRoundPhase.FIRST_MOVER_ACTION:
            return self._first_mover
        if self._phase == PracticeRoundPhase.SECOND_MOVER_ACTION:
            return self._second_mover
        return None

    def pending_actors(self) -> list[CharacterId]:
        """이번 페이즈에 아직 선언하지 않은, 선언할 수 있는 캐릭터 목록.

        체력 0인 캐릭터는 애초에 커맨드를 낼 수 없고(try_expansion_if_valid),
        동료(소환수)는 플레이어가 조작하는 대상이 아니므로 둘 다 제외한다 —
        포함하면 아무도 채울 수 없는 대기 조건이 되어 라운드가 멈춘다."""
        side = self.expected_side()
        if side is None:
            return []
        return [
            char.id
            for char in self._context.get_side_characters(side)
            if char.id not in self._context.companion_owners
            and char.status.curr_hp > 0
            and char.id not in self._declared_this_phase
        ]

    def to_phase(self, phase: PracticeRoundPhase) -> None:
        if phase == PracticeRoundPhase.FIRST_MOVER_ACTION:
            self._context.on_start_round()
            # "적 후행 시" 패시브 중 그 라운드의 피격을 경감할 버프를 거는
            # 쪽. 양 팀이 같은 라운드에 행동하므로 "모든 공격보다 앞"인
            # 지점이 여기뿐이다 (end_round() 참고).
            self._context.buff_container.on_enemy_post_action()
            if self._first_mover is None or self._second_mover is None:
                sides = list(SideType)
                random.shuffle(sides)
                self._first_mover, self._second_mover = sides[0], sides[1]
            else:
                # 첫 라운드만 무작위로 정하고 이후로는 교대한다. 매 라운드
                # 다시 뽑으면 1턴짜리 버프/디버프의 가치가 추첨 결과에 따라
                # 요동친다 — 라운드 종료에 턴이 차감되므로, 후공 페이즈에 건
                # 1턴 효과는 상대가 행동할 기회 없이 그대로 사라진다. 교대는
                # 그 손해를 양 팀에 균등하게 나눈다.
                self._first_mover, self._second_mover = (
                    self._second_mover,
                    self._first_mover,
                )

        elif phase == PracticeRoundPhase.SECOND_MOVER_ACTION:
            pass

        self._phase = phase
        self._declared_this_phase = set()

    def end_round(self) -> None:
        """라운드 종료 버프 처리. 다음 턴은 to_phase(FIRST_MOVER_ACTION)로 시작한다.

        본 전투(RoundManager)는 ENEMY_POST_ACTION 페이즈에서
        on_enemy_post_action()/on_enemy_post_action_resolved()를 호출해
        "적 후행 시" 트리거 패시브(예: 피격 시 [유예된 재앙] 스택을 쌓는
        패시브)를 평가한다. 대련은 PRE/POST 구분 없이 선공/후공을 각각
        process_ally_command()로 즉시 처리하는 대칭 구조라, 본 전투의 두
        훅을 각각 어디에 대응시킬지 직접 정해야 한다:

        - on_enemy_post_action()      → 라운드 시작 (to_phase 참고).
          그 라운드의 공격을 실제로 경감해야 하므로 공격보다 앞서야 한다.
        - on_enemy_post_action_resolved() → 여기.
          damaged_this_round(이번 라운드에 누가 맞았는지)가 확정된 뒤에만
          올바른 값이 나오므로 그 라운드의 모든 행동이 끝난 뒤여야 한다.

        _apply_round_events()가 버프 타이밍만 보고 진영을 가리지 않으므로
        SIDE_1/SIDE_2 양쪽 모두에 대칭으로 적용된다."""
        self._context.buff_container.on_enemy_post_action_resolved()
        self._context.on_finish_round()
        self._phase = None
        self._declared_this_phase = set()

    def process_command(self, command: CharacterCommand) -> CommandProcessResult:
        """커맨드를 검증하고 즉시 전개·적용한다."""
        if self._phase is None:
            raise CommandValidationError("커맨드를 입력할 수 있는 타이밍이 아닙니다.")

        char_side = self._context.get_side(command.user_id)

        # _phase가 None이 아니면 선공/후공도 함께 정해진 뒤다.
        assert self._first_mover is not None and self._second_mover is not None
        expected_side = (
            self._first_mover
            if self._phase == PracticeRoundPhase.FIRST_MOVER_ACTION
            else self._second_mover
        )
        if char_side != expected_side:
            phase_label = self._phase.value
            raise CommandValidationError(
                f"{phase_label} 타이밍에는 {expected_side.value} 캐릭터만 행동할 수 있습니다."
            )

        if command.user_id in self._declared_this_phase:
            raise CommandValidationError(
                f"{command.user_id.name}은(는) 이미 이번 {self._phase.value}에 "
                "행동을 선언했습니다."
            )

        # 대련은 PRE/POST 구분 없이 즉시 전체를 처리한다.
        result = process_ally_command(self._context, command)
        self._context.results.extend(result.part_results)
        self._declared_this_phase.add(command.user_id)
        return result
