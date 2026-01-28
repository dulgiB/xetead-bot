import abc
from dataclasses import dataclass

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import CommandBase


class AdminCommand(CommandBase):
    pass


@dataclass(frozen=True)
class ChangePhaseCommand(AdminCommand):
    target_phase: RoundPhaseType


class AdminCommandData(abc.ABC):
    pass


@dataclass(frozen=True)
class ChangePhaseCommandData(AdminCommandData):
    target_phase: RoundPhaseType


# 무조건 보너스

# 무조건 성공

# 무조건 실패


# 특정 버프 무조건 부여
class ForceAddBuffByNameCommand(AdminCommandData):
    buff_name: str


# 특정 버프 무조건 해제
class ForceRemoveBuffByNameCommand(AdminCommandData):
    buff_name: str
