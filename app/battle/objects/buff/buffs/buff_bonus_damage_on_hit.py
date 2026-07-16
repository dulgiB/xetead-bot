from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.core.commands.models import DamageCalculateData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueSourceType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    DamageData,
    FloatValueModifier,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class BonusDamageOnHitEvent(BuffEvent):
    """피격 시 공격자의 ATK 기반 추가 대미지를 부여한다."""

    source_name: str
    coefficient: float

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
        effect_data = calculator.data_by_effect[effect_seq_number]
        new_items = []
        for damage_data in effect_data.damage_data_list:
            if damage_data.base.target_id == holder:
                extra = DamageData(
                    attacker_id=damage_data.base.attacker_id,
                    target_id=holder,
                    value=BaseValueIndicator(
                        value_source=ValueSourceType.STAT_ATK,
                        coefficient=FloatValueModifier(
                            source_name=self.source_name,
                            value=self.coefficient,
                        ),
                    ),
                    is_magic_attack=damage_data.base.is_magic_attack,
                )
                new_items.append(DamageCalculateData(extra))
        effect_data.damage_data_list.extend(new_items)


class BuffBonusDamageOnHit(BuffBase):
    """피격 시 공격력 기반 고정 대미지를 부여한다.

    value: 추가 대미지 계수 (퍼센트 단위, 예: 50 → ×0.5)
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> BonusDamageOnHitEvent:
        return BonusDamageOnHitEvent(
            condition=self.condition,
            source_name=self.id,
            coefficient=self.value,
        )
