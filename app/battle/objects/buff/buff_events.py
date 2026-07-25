import abc
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional

from battle.objects.buff.conditions import Condition
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.commands.models import CommandPartCalculator


class BuffEventCalculatePriority(Enum):
    PRE = 1
    NORMAL = 2
    POST = 3


@dataclass(frozen=True)
class BuffEvent(abc.ABC):
    condition: Optional[Condition]

    # True로 오버라이드하면 "순수 대미지 수치 수정자"임을 표시한다 — apply()가
    # calculator.data_by_effect[...].damage_data_list를 훑어 attacker_id/
    # target_id가 일치하는 항목의 given_modifiers/received_modifiers에만
    # 추가하고, 그 외의 부수효과(대상 리다이렉트·무효화·새 대미지 항목 추가·
    # 버프 스택 소모 등)가 전혀 없는 이벤트여야 한다. 사거리 내 아군 반격류
    # 같은 제3자 반응형 대미지가 이 값이 True인 이벤트만 골라 격리 재실행해,
    # 해당 반응 대미지 한 건에도 홀더/대상의 평소 주는·받는 대미지 버프가
    # 정상 반영되게 한다(reactive_damage.py 참고). False가 기본값이며,
    # 리다이렉트·무효화 등 부수효과가 있는 이벤트는 절대 True로 바꾸면 안 된다
    # — 격리 재실행 중에 중복 발동하거나 원본 리스트를 건드릴 수 있다.
    is_pure_damage_modifier: ClassVar[bool] = False

    def is_applied(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
    ) -> bool:
        # 조건이 없다면 무조건 적용
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
