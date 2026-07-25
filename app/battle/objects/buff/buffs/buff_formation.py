from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueType
from battle.objects.models import (
    CharacterId,
    FloatValueModifier,
    IntValueModifier,
    ValueModifierBase,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class FormationReceivedDamageModEvent(BuffEvent):
    is_pure_damage_modifier: ClassVar[bool] = True

    value: ValueModifierBase

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
            if damage_data.base.target_id == holder:
                damage_data.received_modifiers.append(self.value)


class BuffFormation(BuffBase):
    """진형 밀집 시 받는 대미지를 감소시키는 팀 버프.

    받는 대미지 증감이라는 점에서는 BuffReceivedDamage와 동일하지만, 다른 스킬
    효과(SkillEffectAddBuffIfHolderHasFormationBuff 등)가 "이 버프를 보유했는지"를
    buff_class_name으로 식별해야 하므로, 다른 캐릭터의 범용 받는 대미지 버프와
    섞이지 않도록 전용 클래스로 둔다.
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> FormationReceivedDamageModEvent:
        if self.value_type == ValueType.INTEGER:
            return FormationReceivedDamageModEvent(
                condition=self.condition,
                value=IntValueModifier(source_name=self.id, value=self.value),
            )
        elif self.value_type == ValueType.PERCENT:
            return FormationReceivedDamageModEvent(
                condition=self.condition,
                value=FloatValueModifier(source_name=self.id, value=self.value),
            )
        else:
            raise ValueError(self.value_type)
