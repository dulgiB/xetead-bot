from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.core.commands.models import DamageCalculateData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueSourceType, ValueType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    DamageData,
    FloatValueModifier,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class CounterDamageOnEnemyMoveEvent(BuffEvent):
    """이동한 적(attacker_or_target)에게 걸린 reference_buff_id 버프의 스택
    수 × coefficient%만큼의 공격 굴림 대미지를 holder가 입힌다. 이 대미지는
    reference_buff_id 자체를 새로 부여하지 않는다(재귀 방지).

    계수는 "coefficient% × 스택"을 미리 곱한 하나의 값이 아니라, 계산식에서
    두 배율의 근거가 각각 드러나도록 FloatValueModifier.display_factors로
    분해해서 보여준다(예: "× (0.7[버프 계수] × 3[디버프])")."""

    coefficient: int
    reference_buff_id: str
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
        if attacker_or_target is None:
            return
        stack = calculator.context.get_buff_stack(
            attacker_or_target, self.reference_buff_id
        )
        if stack <= 0:
            return
        calculator.data_by_effect[effect_seq_number].damage_data_list.append(
            DamageCalculateData(
                DamageData(
                    attacker_id=holder,
                    target_id=attacker_or_target,
                    value=BaseValueIndicator(
                        value_source=ValueSourceType.STAT_ATK_ROLL,
                        coefficient=FloatValueModifier(
                            source_name="계수",
                            value=self.coefficient * stack,
                            display_factors=(
                                (f"{self.buff_label} 계수", self.coefficient),
                                (self.reference_buff_id, stack * 100),
                            ),
                        ),
                    ),
                    triggers_given_damage_passives=False,
                ),
            )
        )


class BuffCounterDamageOnEnemyMove(BuffBase):
    """사거리 내의 적이 이동할 때마다(자발적/강제 이동 모두) 반격 대미지를
    입히는 버프. value_type은 반드시 퍼센트여야 하며, value는 공격 굴림
    계수(스택 1당, 예: 70 → ×0.7)다. 대상의 reference_buff_id 스택이
    0이면 발동하지 않는다(대미지 항목 자체가 생성되지 않음).

    반드시 condition=TargetIsInRangeCondition과 함께 등록해야 한다.
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ENEMY_MOVE

    def create_event(self) -> CounterDamageOnEnemyMoveEvent:
        if self.value_type != ValueType.PERCENT:
            raise ValueError(self.value_type)
        assert self.reference_buff_id is not None
        return CounterDamageOnEnemyMoveEvent(
            condition=self.condition,
            coefficient=self.value,
            reference_buff_id=self.reference_buff_id,
            buff_label=self.display_id_label(),
        )
