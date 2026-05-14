from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, CombatStatType, ValueType
from battle.objects.models import CharacterId, IntValueModifier

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class AtkModEvent(BuffEvent):
    value: IntValueModifier

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
        calculator.buffed_stats_by_character[holder].stat_bonuses[
            CombatStatType.ATK
        ].append(self.value)


class BuffAtk(BuffBase):
    """공격력 증가/감소"""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> AtkModEvent:
        if self.value_type == ValueType.INTEGER:
            return AtkModEvent(
                condition=self.condition,
                value=IntValueModifier(source_name=self.id, value=self.value),
            )
        else:
            raise ValueError(self.value_type)
