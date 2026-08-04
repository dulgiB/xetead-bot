from dataclasses import dataclass

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import CommandPart
from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import CharacterId

ADMIN_ID = CharacterId("시스템")


# Admin은 파트 단위로 커맨드를 입력하지 않으므로 커맨드 = 파트
@dataclass(frozen=True)
class AdminCommand(CommandPart):
    pass


@dataclass(frozen=True)
class ChangePhaseCommand(AdminCommand):
    target_phase: RoundPhaseType


# Force* 커맨드의 targets는 항상 CharacterId만 담지만, list는 무공변이라
# CommandPart.targets(list[CharacterId | BattlefieldColumnIndex])를 하위
# 클래스에서 list[CharacterId]로 좁혀 재선언할 수 없다(mypy invariance 오류) —
# 상속받은 타입 그대로 두고, 실제 사용처(command_expanders.py)에서 cast한다.
@dataclass(frozen=True)
class ForceMoveCommand(AdminCommand):
    to_position: BattlefieldColumnIndex


@dataclass(frozen=True)
class ForceDamageCommand(AdminCommand):
    damage_value: int


@dataclass(frozen=True)
class ForceHealCommand(AdminCommand):
    heal_value: int


# 특정 버프 무조건 부여
@dataclass(frozen=True)
class ForceAddBuffByIdCommand(AdminCommand):
    buff_id: str


# 특정 버프 무조건 해제
@dataclass(frozen=True)
class ForceRemoveBuffByIdCommand(AdminCommand):
    buff_id: str
