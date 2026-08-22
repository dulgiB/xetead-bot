from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.core.commands.models import DamageCalculateData, DamageData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueSourceType, ValueType
from battle.objects.models import BaseValueIndicator, CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class DamageOverTimeEvent(BuffEvent):
    value: int
    buff_label: str

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
        calculator.data_by_effect[effect_seq_number].damage_data_list.append(
            DamageCalculateData(
                DamageData(
                    attacker_id=attacker_or_target,
                    target_id=holder,
                    value=BaseValueIndicator(ValueSourceType.FIXED, self.value),
                    triggers_received_damage_passives=False,
                    source_label=f"{self.buff_label}: {attacker_or_target.name}",
                ),
            )
        )


class BuffDamageOverTime(BuffBase):
    """매 라운드 종료 시 고정 대미지를 입힌다. value_type은 반드시 정수여야 한다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ROUND_END

    def create_event(self) -> DamageOverTimeEvent:
        if self.value_type is not None and self.value_type != ValueType.INTEGER:
            raise ValueError(self.value_type)
        return DamageOverTimeEvent(
            condition=self.condition,
            value=self.value,
            buff_label=self.display_id_label(),
        )
