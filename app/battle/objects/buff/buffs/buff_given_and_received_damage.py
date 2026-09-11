from dataclasses import dataclass
from typing import ClassVar, TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueType
from battle.objects.models import CharacterId, FloatValueModifier

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class GivenAndReceivedDamageModEvent(BuffEvent):
    """holder가 공격자면 주는 대미지를, holder가 대상이면 받는 대미지를
    함께 조정한다(BuffGivenDamage + BuffReceivedDamage를 한 버프로 합친
    형태). 두 비율은 "버프" 시트의 value(주는 대미지)/value_2(받는 대미지)
    컬럼(둘 다 퍼센트로 해석)에서 온다."""

    is_pure_damage_modifier: ClassVar[bool] = True

    given_percent: int
    received_percent: int

    # 표시용 라벨. 여러 캐릭터가 공유하는 클래스라 이름을 하드코딩하지 않고
    # 이 버프를 등록한 시트 행의 id를 그대로 쓴다.
    label: str

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
        for damage_data in calculator.data_by_effect[
            effect_seq_number
        ].damage_data_list:
            if damage_data.base.attacker_id == holder:
                damage_data.given_modifiers.append(
                    FloatValueModifier(source_name=self.label, value=self.given_percent)
                )
            if damage_data.base.target_id == holder:
                damage_data.received_modifiers.append(
                    FloatValueModifier(
                        source_name=self.label, value=self.received_percent
                    )
                )


class BuffGivenAndReceivedDamage(BuffBase):
    """주는 대미지가 value%만큼 증가하는 대신 받는 대미지도 value_2%만큼
    함께 증가하는 트레이드오프 버프."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> GivenAndReceivedDamageModEvent:
        if self.value_type != ValueType.PERCENT:
            raise ValueError(self.value_type)
        return GivenAndReceivedDamageModEvent(
            condition=self.condition,
            label=self.id,
            given_percent=self.value,
            received_percent=self.value_2,
        )
