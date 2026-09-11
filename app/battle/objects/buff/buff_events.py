import abc
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional

from battle.objects.buff.conditions import Condition
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.command_calculator import CommandPartCalculator


class BuffEventCalculatePriority(Enum):
    PRE = 1
    NORMAL = 2
    POST = 3


@dataclass(frozen=True)
class BuffEvent(abc.ABC):
    condition: Optional[Condition]

    # "given/received_modifiers에 값만 더하고 다른 부수효과가 전혀 없는"
    # 이벤트라는 표시. 제3자 반응형 대미지가 이 값이 True인 이벤트만 골라
    # 격리 재실행한다(reactive_damage.py 참고) — 리다이렉트·무효화 등
    # 부수효과가 있는 이벤트를 True로 바꾸면 거기서 중복 발동한다.
    is_pure_damage_modifier: ClassVar[bool] = False

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        if self.condition is None:
            return True
        return self.condition.is_applied(context, holder, attacker_or_target)

    @abc.abstractmethod
    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        pass

    @property
    @abc.abstractmethod
    def priority(self) -> BuffEventCalculatePriority:
        pass
