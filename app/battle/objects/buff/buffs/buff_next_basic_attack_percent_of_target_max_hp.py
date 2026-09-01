from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Optional

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import (
    ActionType,
    BuffApplyTiming,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import BaseValueIndicator, CharacterId, FloatValueModifier

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class NextBasicAttackPercentOfTargetMaxHpEvent(BuffEvent):
    """holder가 기본 공격(스킬이 아님)을 가할 때만 발동해, 그 대미지 값을
    대상 최대체력의 value_percent%로 완전히 대체한다. holder가 피격당할
    때는 attacker_id != holder라 발동하지 않는다."""

    buff_label: str
    value_percent: int

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        if calculator.action_type != ActionType.ATTACK:
            return

        for damage_calc in calculator.data_by_effect[
            effect_seq_number
        ].damage_data_list:
            if damage_calc.base.attacker_id != holder:
                continue
            damage_calc.base = replace(
                damage_calc.base,
                value=BaseValueIndicator(
                    value_source=ValueSourceType.TARGET_MAX_HP,
                    coefficient=FloatValueModifier(
                        source_name=self.buff_label, value=self.value_percent
                    ),
                ),
            )


class BuffNextBasicAttackPercentOfTargetMaxHp(BuffBase):
    """자신의 다음 기본 공격이 대상 최대체력의 value% 대미지로 변경된다.
    비율은 "버프" 시트의 value 컬럼(value_type=퍼센트)으로 관리한다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> NextBasicAttackPercentOfTargetMaxHpEvent:
        if self.value_type != ValueType.PERCENT:
            raise ValueError(self.value_type)
        return NextBasicAttackPercentOfTargetMaxHpEvent(
            condition=self.condition,
            buff_label=self.display_id_label(),
            value_percent=self.value,
        )
