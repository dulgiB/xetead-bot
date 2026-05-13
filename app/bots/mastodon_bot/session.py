from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import CharacterCommand
from battle.core.round_manager import RoundManager
from battle.objects.buff.models import BuffData
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.skill.models import SkillData
from spreadsheets.models.battle import CharacterDataFromSpreadsheet

_PHASE_ORDER: list[RoundPhaseType] = [
    RoundPhaseType.ENEMY_PRE_ACTION,
    RoundPhaseType.ALLY_ACTION,
    RoundPhaseType.ENEMY_POST_ACTION,
    RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY,
]


class BattleSession:
    def __init__(
        self,
        buff_dict: dict[str, BuffData],
        skill_dict: dict[str, SkillData],
    ) -> None:
        self.context = BattlefieldContext(buff_dict, skill_dict)
        self.manager = RoundManager(self.context)
        self.started = False
        self._phase_idx = 0

    @property
    def current_phase(self) -> RoundPhaseType:
        return _PHASE_ORDER[self._phase_idx]

    def add_character(
        self,
        data: CharacterDataFromSpreadsheet,
        faction: FactionType,
        column: BattlefieldColumnIndex,
    ) -> None:
        self.context.add_character(data, faction, column)

    def start(self) -> None:
        self.started = True
        self.manager.process_command(
            ChangePhaseCommand(
                type_=ActionType.ADMIN,
                target_phase=RoundPhaseType.ENEMY_PRE_ACTION,
            )
        )

    def advance_phase(self) -> RoundPhaseType:
        self._phase_idx = (self._phase_idx + 1) % len(_PHASE_ORDER)
        phase = self.current_phase
        self.manager.process_command(
            ChangePhaseCommand(type_=ActionType.ADMIN, target_phase=phase)
        )
        return phase

    def process_command(self, command: CharacterCommand) -> None:
        self.manager.process_command(command)
