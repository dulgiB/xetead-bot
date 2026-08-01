from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class ReduceCostNextRoundEvent(BuffEvent):
    amount: int

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
        character = calculator.context.characters.get(holder)
        if character is None:
            return
        character.status.remaining_cost = max(
            0, character.status.remaining_cost - self.amount
        )


class BuffReduceCostNextRound(BuffBase):
    """다음 라운드 시작(코스트 전액 회복 직후) 시점에 1회, value만큼 코스트를
    깎는다. 반드시 duration_turn_value=2로 등록해야 한다 — 부여된 라운드가
    끝날 때 한 번, 그 다음 라운드가 끝날 때 한 번, 총 두 번 턴이 차감되어야
    "다음 라운드 시작" 시점에 정확히 한 번만 발동(그 시점엔 아직 살아있음)한
    뒤 그 라운드가 끝나며 제거된다. BattlefieldContext.on_start_round()가
    코스트 전액 회복 → ON_ROUND_START 버프 순서로 처리하므로, 이 버프가
    회복 직후의 remaining_cost를 실제로 깎을 수 있다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ROUND_START

    def create_event(self) -> ReduceCostNextRoundEvent:
        if self.value_type != ValueType.INTEGER:
            raise ValueError(self.value_type)
        return ReduceCostNextRoundEvent(condition=self.condition, amount=self.value)
