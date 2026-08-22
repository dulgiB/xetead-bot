from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.buff.damage_factory import make_coefficient_damage_calc
from battle.objects.define import BuffApplyTiming, ValueSourceType, ValueType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class DamagePerReferencedBuffStackEvent(BuffEvent):
    """라운드 종료 시, holder에게 걸린 reference_buff_id 버프의 현재 스택
    수(턴 차감 전 기준) × coefficient 만큼 고정 대미지를 입힌다.

    스택 수를 coefficient로 미리 곱해 FIXED 값으로 넘기면 계산식이 표시되지
    않으므로(FIXED는 coefficient를 적용/표시하지 않음), REFERENCED_BUFF_STACK
    value_source + coefficient 조합을 써서 "{스택}[{버프id}] × {배율}" 형태의
    계산식이 그대로 드러나게 한다.

    attacker_id를 given_by(버프를 건 캐릭터)로 남기는 것은 표시/귀속 목적일
    뿐, given_by가 지금 이 순간 "공격"을 한 것은 아니다. triggers_given_
    damage_passives=False로 막아두지 않으면, given_by가 "대미지를 줄 때마다"
    발동하는 패시브(BuffApplyDebuffOnDealingDamage 등)를 라운드마다 다시
    유발해 의도치 않게 reference_buff_id 스택이 재적립되는 순환이 생긴다."""

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
        stack = calculator.context.get_buff_stack(holder, self.reference_buff_id)
        if stack <= 0:
            return
        calculator.data_by_effect[effect_seq_number].damage_data_list.append(
            make_coefficient_damage_calc(
                attacker_id=attacker_or_target,
                target_id=holder,
                value_source=ValueSourceType.REFERENCED_BUFF_STACK,
                source_name="계수",
                coefficient_value=self.coefficient * 100,
                consumed_buff_id=self.reference_buff_id,
                triggers_given_damage_passives=False,
                triggers_received_damage_passives=False,
                source_label=f"{self.buff_label}: {attacker_or_target.name}",
            )
        )


class BuffDamageOverTimePerReferencedBuffStack(BuffBase):
    """매 라운드 종료 시 다른 버프(reference_buff_id)의 스택 수에 비례한
    고정 대미지를 입힌다. value_type은 반드시 정수여야 하며, value는
    스택당 대미지 계수다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ROUND_END

    def create_event(self) -> DamagePerReferencedBuffStackEvent:
        if self.value_type is not None and self.value_type != ValueType.INTEGER:
            raise ValueError(self.value_type)
        assert self.reference_buff_id is not None
        return DamagePerReferencedBuffStackEvent(
            condition=self.condition,
            coefficient=self.value,
            reference_buff_id=self.reference_buff_id,
            buff_label=self.display_id_label(),
        )
