from typing import Optional

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import CharacterCommand
from battle.core.round_manager import RoundManager
from battle.objects.buff.models import BuffData
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.item.models import ItemData
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.models import SkillData
from spreadsheets.inventory import Inventory
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet

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
        passive_skill_dict: Optional[dict[str, PassiveSkillData]] = None,
        item_dict: Optional[dict[str, ItemData]] = None,
        inventory: Optional[Inventory] = None,
    ) -> None:
        self.context = BattlefieldContext(
            buff_dict, skill_dict, passive_skill_dict, item_dict, inventory
        )
        self.manager = RoundManager(self.context)
        self.started: bool = False
        self.name: Optional[str] = None
        self._phase_idx: int = 0
        self.round_n: int = 0

    @property
    def current_phase(self) -> RoundPhaseType:
        return _PHASE_ORDER[self._phase_idx]

    def add_character(
        self,
        data: CombatCharacterDataFromSpreadsheet,
        faction: FactionType,
        column: BattlefieldColumnIndex,
    ) -> None:
        self.context.add_character(data, faction, column)

    def restore_progress(self, round_n: int, phase: RoundPhaseType) -> None:
        """봇 재기동 복원 전용: `start()`처럼 1라운드+ENEMY_PRE_ACTION으로
        리셋하지 않고, 크래시 이전 라운드/페이즈 값을 그대로 대입한다.
        `on_battle_start()`/`ChangePhaseCommand`를 재실행하지 않으므로
        페이즈 전환 부작용(DoT 등)이 중복 적용되지 않는다 — 캐릭터를
        모두 add_character()한 뒤, 필요하면 `context.on_battle_start()`를
        별도로 한 번만 호출해 배틀-스타트 트리거만 새로 적용한다."""
        self.started = True
        self.round_n = round_n
        self._phase_idx = _PHASE_ORDER.index(phase)
        self.manager.set_phase_for_restore(phase)

    def start(self) -> None:
        self.started = True
        self.round_n = 1
        self.context.on_battle_start()
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
        if phase == RoundPhaseType.ENEMY_PRE_ACTION:
            self.round_n += 1
        return phase

    def process_command(self, command: CharacterCommand) -> None:
        self.manager.process_command(command)
