from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class SacrificeEvent(BuffEvent):
    """리다이렉트 시 카운트 차감 외에 추가 효과 없음."""

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.POST

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        pass


class BuffSacrifice(BuffBase):
    """희생 방어. applied_to(보호 대상)가 공격받을 시 given_by(보호자)가 대신 맞는다.

    count 차감은 리다이렉트 시점에 수행되므로 스프레드시트에서
    duration_count_deduct_condition은 비워도 된다.
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> SacrificeEvent:
        return SacrificeEvent(condition=self.condition)

    def get_sacrifice_override(self) -> Optional[CharacterId]:
        return self.given_by
