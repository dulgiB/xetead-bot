import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from battle.core.commands.models import DamageCalculateData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueSourceType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    DamageData,
    ValueWithModifiers,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class ReflectEvent(BuffEvent):
    _REFLECT_PERCENT: ClassVar[int] = 40

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.POST

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        data_list = calculator.data_by_effect[effect_seq_number].damage_data_list
        to_nullify = [d for d in data_list if d.base.target_id == holder]
        if not to_nullify:
            return

        # 반사 대미지는 공격자의 공격 굴림 + 주는 대미지 버프/디버프만 반영한
        # 고정값이다. 피격자(자신)가 받는 대미지 버프/디버프와, 되돌려받을 때
        # 공격자가 받는 대미지 버프/디버프는 모두 반영하지 않는다 — 그래서
        # received_modifiers는 참조도, 새로 부여하지도 않는다.
        reflected: list[DamageCalculateData] = []
        for damage_calc in to_nullify:
            attacker_id = damage_calc.base.attacker_id
            if attacker_id not in calculator.context.characters:
                continue
            base_value = ValueWithModifiers(
                damage_calc.base.value, damage_calc.given_modifiers, []
            ).get_value(calculator, attacker_id, holder, effect_seq_number)
            reflect_value = math.floor(base_value * self._REFLECT_PERCENT / 100)
            reflected.append(
                DamageCalculateData(
                    base=DamageData(
                        attacker_id=holder,
                        target_id=attacker_id,
                        value=BaseValueIndicator(
                            value_source=ValueSourceType.FIXED, value=reflect_value
                        ),
                    )
                )
            )

        for damage_calc in to_nullify:
            data_list.remove(damage_calc)
        data_list.extend(reflected)


class BuffReflect(BuffBase):
    """반사"""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> ReflectEvent:
        return ReflectEvent(condition=self.condition)
