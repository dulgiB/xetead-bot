from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.core.commands.models import CommandCalculator
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, CombatStatType, ValueType
from battle.objects.models import CharacterId, FloatValueModifier, IntValueModifier

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class AtkModEvent(BuffEvent):
    value: IntValueModifier | FloatValueModifier

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: BattlefieldContext,
        calculator: CommandCalculator,
    ) -> None:
        calculator.buffed_stats_by_character[holder].stat_bonuses[
            CombatStatType.ATK
        ].append(self.value)


@dataclass
class BuffAtk(BuffBase):
    """공격력 증가/감소"""

    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ATTACK}

    def apply(self) -> AtkModEvent:
        if self.value_type == ValueType.INTEGER:
            return AtkModEvent(
                condition=self.condition,
                value=IntValueModifier(self.value),
            )
        elif self.value_type == ValueType.PERCENT:
            return AtkModEvent(
                condition=self.condition,
                value=FloatValueModifier(self.value),
            )
        else:
            raise ValueError(self.value_type)
