from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_expanders import expand_admin_command
from battle.core.command_processors import (
    process_admin_command,
    process_ally_command,
    process_enemy_command_on_pre_action,
    try_process_enemy_command_on_post_action,
)
from battle.core.commands.admin import AdminCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import CharacterCommand, CommandPartProcessResult
from battle.exceptions import CommandValidationError
from battle.objects.define import FactionType
from battle.objects.models import CharacterId


class RoundManager:
    def __init__(self, context: BattlefieldContext) -> None:
        self._context = context
        self._phase = RoundPhaseType.ENEMY_PRE_ACTION
        self._enemy_command_list: dict[CharacterId, list[CharacterCommand]] = {}
        self._last_post_action_results: dict[
            CharacterId, list[CommandPartProcessResult]
        ] = {}

    def get_enemy_declared_commands(self) -> dict[CharacterId, list[CharacterCommand]]:
        return self._enemy_command_list

    def get_last_post_action_results(
        self,
    ) -> dict[CharacterId, list[CommandPartProcessResult]]:
        """가장 최근 ENEMY_POST_ACTION 정산에서 적군 개별 캐릭터가 낸
        결과(대미지/힐/계산식 포함)를 반환한다. 답글용 game_post 텍스트
        조립에 쓰인다."""
        return self._last_post_action_results

    def to_phase(self, phase: RoundPhaseType):
        self._phase = phase

        if phase == RoundPhaseType.ENEMY_PRE_ACTION:
            self._context.on_start_round()

        elif phase == RoundPhaseType.ALLY_ACTION:
            pass

        elif phase == RoundPhaseType.ENEMY_POST_ACTION:
            # 적의 지연된 공격이 실제로 적용되기 전에 발동한다. 이 시점에 실제
            # 버프(ON_ACTION 타이밍)를 새로 부여하는 패시브는 그 버프가 뒤이어
            # 처리되는 이 라운드의 공격에 곧바로 반영되어야 한다.
            self._context.buff_container.on_enemy_post_action()
            self._last_post_action_results = {}
            for user_id, remaining_commands in self._enemy_command_list.items():
                post_results = try_process_enemy_command_on_post_action(
                    self._context, user_id, remaining_commands
                )
                self._context.results.extend(post_results)
                self._last_post_action_results[user_id] = post_results
            # 적의 공격이 모두 적용된 뒤에 발동한다. damaged_this_round(이번
            # 라운드에 누가 맞았는지)에 반응하는 패시브 전용 타이밍이라, 위
            # on_enemy_post_action()과 달리 이 시점에만 평가돼야 하는 패시브만
            # 선택된다(PassiveSkillWrapperBuff.timing 참고).
            self._context.buff_container.on_enemy_post_action_resolved()

        elif phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
            self._context.on_finish_round()
            self._enemy_command_list.clear()

        else:
            raise ValueError(f"Unknown phase: {phase}")

    def process_command(self, command: CharacterCommand | AdminCommand | None) -> None:
        if command is None:
            return

        print(command)

        if isinstance(command, AdminCommand):
            expanded_command = expand_admin_command(command, self._context)
            process_admin_command(self, expanded_command)

        elif isinstance(command, CharacterCommand):
            if self._context.characters[command.user_id].faction == FactionType.ALLY:
                if self._phase != RoundPhaseType.ALLY_ACTION:
                    raise CommandValidationError(
                        "커맨드를 입력할 수 있는 타이밍이 아닙니다."
                    )

                ally_command_result = process_ally_command(self._context, command)
                self._context.results.extend(ally_command_result.part_results)

            elif self._context.characters[command.user_id].faction == FactionType.ENEMY:
                if self._phase != RoundPhaseType.ENEMY_PRE_ACTION:
                    raise CommandValidationError(
                        "커맨드를 입력할 수 있는 타이밍이 아닙니다."
                    )

                enemy_pre_command_result = process_enemy_command_on_pre_action(
                    self._context, command, self._enemy_command_list
                )
                self._context.results.extend(enemy_pre_command_result.part_results)
