from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class StackingMarkNoopEvent(BuffEvent):
    """단독으로는 아무 효과가 없는 순수 적층 마커다. 다른 버프/스킬이 스택
    수를 조회해 대미지 등에 활용하므로 여기서는 아무 일도 하지 않는다."""

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        pass


class BuffStackingMark(BuffBase):
    """단독으로는 아무 효과가 없는 순수 적층 마커 버프/디버프.

    재앙(BuffCatastrophe)/균열(BuffFracture)과 같은 목적이지만, 다른 캐릭터의
    마커와 buff_class_name 기반 식별(BuffUid)이 충돌하지 않아야 하는 경우
    (동일 부여자가 이 마커와 다른 마커를 동시에 다른 대상에게 부여하는 등)
    전용으로 쓴다. 다른 버프/스킬 효과가 이 버프의 id로 스택 수를 조회해
    활용한다.
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ROUND_END

    def create_event(self) -> StackingMarkNoopEvent:
        return StackingMarkNoopEvent(condition=self.condition)
