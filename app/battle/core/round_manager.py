from battle.admin_utils import AdminCommand
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_expanders import expand_admin_command, expand_character_command
from battle.core.command_processors import (
    process_admin_command,
    process_ally_command,
    process_enemy_command,
)
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import (
    ActionCommandPart,
    CharacterCommand,
    CommandPartBase,
    CommandPartData,
    ItemCommandPart,
)
from battle.exceptions import CommandValidationError
from battle.objects.define import FactionType
from battle.objects.models import CharacterId


class RoundManager:
    def __init__(self, context: BattlefieldContext) -> None:
        self._context = context
        self._phase = RoundPhaseType.ENEMY_PRE_ACTION
        self._acted_characters: set[CharacterId] = set()

        self._ally_commands: list[CommandPartData] = []
        self._enemy_commands: list[CommandPartData] = []

    def to_phase(self, phase: RoundPhaseType):
        self._phase = phase

        if phase == RoundPhaseType.ENEMY_PRE_ACTION:
            pass
        elif phase == RoundPhaseType.ALLY_ACTION:
            pass
        elif phase == RoundPhaseType.ENEMY_POST_ACTION:
            pass
        elif phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
            self._context.buff_container.on_round_end()
            self._acted_characters.clear()
            self._ally_commands.clear()
            self._enemy_commands.clear()
        else:
            raise ValueError(f"Unknown phase: {phase}")

    def process_command(self, command: CharacterCommand | AdminCommand | None) -> None:
        if command is None:
            return

        print(command)

        if isinstance(command, AdminCommand):
            expanded_command = expand_admin_command(command)
            process_admin_command(self, expanded_command)

        elif isinstance(command, CharacterCommand):
            if self._context.characters[command.user_id].faction == FactionType.ALLY:
                if self._phase != RoundPhaseType.ALLY_ACTION:
                    raise CommandValidationError(
                        "커맨드를 입력할 수 있는 타이밍이 아닙니다."
                    )

                process_ally_command(self._context, command)

            elif self._context.characters[command.user_id].faction == FactionType.ENEMY:
                if self._phase != RoundPhaseType.ENEMY_PRE_ACTION:
                    raise CommandValidationError(
                        "커맨드를 입력할 수 있는 타이밍이 아닙니다."
                    )

                process_enemy_command(self._context, command)
