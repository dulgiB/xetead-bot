import random

from battle.core.command_processors import process_ally_command
from battle.core.commands.models import CharacterCommand, CommandProcessResult
from battle.exceptions import CommandValidationError
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType


class PracticeRoundManager:
    """
    대련 턴 진행 관리자.

    턴 흐름:
      to_phase(FIRST_MOVER_ACTION)  — 라운드 시작 + 선공/후공 무작위 결정
      process_command(...)           — 선공 측 캐릭터 커맨드 즉시 처리
      to_phase(SECOND_MOVER_ACTION) — 후공 페이즈로 전환
      process_command(...)           — 후공 측 캐릭터 커맨드 즉시 처리
      end_round()                    — 라운드 종료 버프 처리 후 다음 턴 대기
    """

    def __init__(self, context: PracticeBattlefieldContext) -> None:
        self._context = context
        self._phase: PracticeRoundPhase | None = None
        self._first_mover: SideType | None = None
        self._second_mover: SideType | None = None

    @property
    def first_mover(self) -> SideType | None:
        return self._first_mover

    @property
    def second_mover(self) -> SideType | None:
        return self._second_mover

    @property
    def phase(self) -> PracticeRoundPhase | None:
        return self._phase

    def to_phase(self, phase: PracticeRoundPhase) -> None:
        if phase == PracticeRoundPhase.FIRST_MOVER_ACTION:
            # 라운드 시작 처리 + 선공/후공 무작위 결정
            self._context.on_start_round()
            sides = list(SideType)
            random.shuffle(sides)
            self._first_mover, self._second_mover = sides[0], sides[1]

        elif phase == PracticeRoundPhase.SECOND_MOVER_ACTION:
            pass

        self._phase = phase

    def end_round(self) -> None:
        """라운드 종료 버프 처리. 다음 턴은 to_phase(FIRST_MOVER_ACTION)로 시작한다."""
        self._context.on_finish_round()
        self._phase = None

    def process_command(self, command: CharacterCommand) -> CommandProcessResult:
        """
        커맨드를 검증하고 즉시 전개·적용한다.
        선공 페이즈에는 선공 팀, 후공 페이즈에는 후공 팀만 행동할 수 있다.
        """
        if self._phase is None:
            raise CommandValidationError("커맨드를 입력할 수 있는 타이밍이 아닙니다.")

        char_side = self._context.get_side(command.user_id)

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

        # 대련은 PRE/POST 구분 없이 즉시 전체 처리 (process_ally_command 재사용)
        result = process_ally_command(self._context, command)
        self._context.results.extend(result.part_results)
        return result
