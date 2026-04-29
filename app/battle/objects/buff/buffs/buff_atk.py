from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.core.commands.models import CommandPartCalculator
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, CombatStatType, ValueType
from battle.objects.models import (
    CharacterId,
    FloatValueModifier,
    IntValueModifier,
    ValueModifierBase,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class AtkModEvent(BuffEvent):
    value: ValueModifierBase

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        context: BattlefieldContext,
        calculator: CommandPartCalculator,
    ) -> None:
        calculator.buffed_stats_by_character[holder].stat_bonuses[
            CombatStatType.ATK
        ].append(self.value)


@dataclass
class BuffAtk(BuffBase):
    """공격력 증가/감소"""

    @property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_ATTACK}

    def create_event(self) -> AtkModEvent:
        if self.value_type == ValueType.INTEGER:
            return AtkModEvent(
                condition=self.condition,
                value=IntValueModifier(source_name=self.name, value=self.value),
            )
        elif self.value_type == ValueType.PERCENT:
            return AtkModEvent(
                condition=self.condition,
                value=FloatValueModifier(source_name=self.name, value=self.value),
            )
        else:
            raise ValueError(self.value_type)
