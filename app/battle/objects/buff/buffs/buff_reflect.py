import math
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
    ValueWithModifiers,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class ReflectEvent(BuffEvent):
    # 무효화 로그(예: "[반사] 소모, 대미지 없음")에 표시할 버프 라벨.
    buff_label: str
    # "버프"/"버프_패시브" 시트의 value(value_type=퍼센트)에서 온다.
    reflect_percent: int

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
            value_with_modifiers = ValueWithModifiers(
                damage_calc.base.value, damage_calc.given_modifiers, []
            )
            base_value = value_with_modifiers.get_value(
                calculator, attacker_id, holder, effect_seq_number
            )
            reflect_value = math.floor(base_value * self.reflect_percent / 100)
            # 원래 대미지 계산식(공격 굴림 + 주는 대미지 버프)에 "× 반사 계수"를
            # 덧붙여 답글에 어떻게 반사량이 나왔는지 그대로 보여준다. 계산할 게
            # 전혀 없어(고정 대미지 등) format_calculation()이 None을 반환하면
            # 최종 수치만이라도 보여준다.
            given_calc_display = value_with_modifiers.format_calculation() or str(
                base_value
            )
            reflected.append(
                DamageCalculateData(
                    base=DamageData(
                        attacker_id=holder,
                        target_id=attacker_id,
                        value=BaseValueIndicator(
                            value_source=ValueSourceType.FIXED, value=reflect_value
                        ),
                        triggers_received_damage_passives=False,
                        source_label=f"{self.buff_label}: {holder.name}",
                    ),
                    roll_display=(
                        f"{given_calc_display} × "
                        f"{self.reflect_percent / 100:g}[반사 계수]"
                    ),
                )
            )

        for damage_calc in to_nullify:
            data_list.remove(damage_calc)
        data_list.extend(reflected)

        calculator.data_by_effect[effect_seq_number].nullified_effect_list.append(
            (holder, f"[{self.buff_label}] 소모, 대미지 없음")
        )


class BuffReflect(BuffBase):
    """반사. 반사 배율은 "버프"/"버프_패시브" 시트의 value 컬럼(반드시
    value_type=퍼센트)으로 관리한다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> ReflectEvent:
        if self.value_type != ValueType.PERCENT:
            raise ValueError(self.value_type)
        return ReflectEvent(
            condition=self.condition,
            buff_label=self.display_id_label(),
            reflect_percent=self.value,
        )
