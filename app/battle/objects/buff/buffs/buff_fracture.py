from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class FractureNoopEvent(BuffEvent):
    """[균열]은 자연적으로 발동하는 효과가 없는 순수 적층 마커 디버프다. 스킬 효과
    (SkillEffectDamageByDebuffStackTier 등)가 스택을 직접 조회해 활용하므로 여기서는
    아무 일도 하지 않는다."""

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


class BuffFracture(BuffBase):
    """[균열]: 디버프. 최대 5회까지 적층되며, 단독으로는 아무 효과가 없는 순수
    마커다. 다른 스킬/패시브가 스택 여부·수치를 조회해 대미지 보너스나 계수
    분기에 활용한다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ROUND_END

    def create_event(self) -> FractureNoopEvent:
        return FractureNoopEvent(condition=self.condition)
