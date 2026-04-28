from dataclasses import dataclass

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import CommandPart


# Admin은 파트 단위로 커맨드를 입력하지 않으므로 커맨드 = 파트
class AdminCommand(CommandPart):
    pass


@dataclass(frozen=True)
class ChangePhaseCommand(AdminCommand):
    target_phase: RoundPhaseType


# 무조건 보너스

# 무조건 성공

# 무조건 실패


# 특정 버프 무조건 부여
class ForceAddBuffByNameCommand(AdminCommand):
    buff_name: str


# 특정 버프 무조건 해제
class ForceRemoveBuffByNameCommand(AdminCommand):
    buff_name: str
