from dataclasses import dataclass
from time import monotonic
from typing import Optional

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.round_manager import RoundManager
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from spreadsheets.models.battle import CharacterDataFromSpreadsheet

from bots.discord_bot.consts import PHASE_ORDER, SESSION_TIMEOUT_SECONDS


@dataclass
class _CharRecord:
    """스킬 재지정을 위해 원본 데이터를 보관."""

    data: CharacterDataFromSpreadsheet
    faction: FactionType
    column: BattlefieldColumnIndex


class BattleSession:
    def __init__(self, buff_dict, skill_dict):
        self.context = BattlefieldContext(buff_dict, skill_dict)
        self.manager = RoundManager(self.context)
        self.started = False
        self._phase_idx = 0
        self._records: dict[str, _CharRecord] = {}
        self.last_activity: float = monotonic()

    def touch(self) -> None:
        """활동 시각을 현재로 갱신한다."""
        self.last_activity = monotonic()

    def is_expired(self) -> bool:
        return monotonic() - self.last_activity > SESSION_TIMEOUT_SECONDS

    @property
    def current_phase(self) -> RoundPhaseType:
        return PHASE_ORDER[self._phase_idx]

    def advance_phase(self) -> RoundPhaseType:
        self._phase_idx = (self._phase_idx + 1) % len(PHASE_ORDER)
        phase = self.current_phase
        self.manager.process_command(
            ChangePhaseCommand(type_=ActionType.ADMIN, target_phase=phase)
        )
        self.touch()
        return phase

    def add_character(
        self,
        data: CharacterDataFromSpreadsheet,
        faction: FactionType,
        col: BattlefieldColumnIndex,
    ) -> None:
        self.context.add_character(data, faction, col)
        self._records[data.name] = _CharRecord(data, faction, col)
        self.touch()

    def has_character(self, name: str) -> bool:
        return name in self._records

    def set_skills(
        self,
        name: str,
        passive_id: Optional[str],
        skill1_id: Optional[str],
        skill2_id: Optional[str],
        skill3_id: Optional[str],
    ) -> None:
        """캐릭터를 제거 후 스킬이 반영된 버전으로 재추가한다."""
        rec = self._records[name]
        new_data = CharacterDataFromSpreadsheet(
            name=rec.data.name,
            mastodon_id=rec.data.mastodon_id,
            curr_hp=rec.data.curr_hp,
            max_hp=rec.data.max_hp,
            atk=rec.data.atk,
            attack_range=rec.data.attack_range,
            m_res=rec.data.m_res,
            is_magic_attacker=rec.data.is_magic_attacker,
            max_cost=rec.data.max_cost,
            passive_buff_id=passive_id or "",
            skill_1_id=skill1_id or "",
            skill_2_id=skill2_id or "",
            skill_3_id=skill3_id or "",
        )
        self.context.remove_character(CharacterId(name))
        self.context.add_character(new_data, rec.faction, rec.column)
        self._records[name] = _CharRecord(new_data, rec.faction, rec.column)
        self.touch()
