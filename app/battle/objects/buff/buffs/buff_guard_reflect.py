import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar, Optional

from battle.core.commands.models import DamageCalculateData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueSourceType, ValueType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    DamageData,
    FloatValueModifier,
    ValueWithModifiers,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class GuardReflectEvent(BuffEvent):
    """holder가 받는 물리 대미지는 _PHYSICAL_REDUCTION_PERCENT%만큼 경감하고,
    마법 대미지는 완전히 무효화한다. applies_to_fixed=True라 도트/반격 등
    FIXED 값 파생 대미지에도 동일하게 적용된다. 공격자가 같은 스킬로 함께
    부여하는 버프(부가 효과)는 damage_data_list와 별도로 처리되는
    buff_add_list를 통해 그대로 유지된다.

    물리/마법 공격 모두, 이 버프의 경감·무효화를 적용하기 전 원래 대미지의
    reflect_percent%를 공격자에게 반사한다 — 마법 공격은 홀더가 실제로
    받는 대미지가 0이 되지만, 반사량은 그 이전(경감 전) 값 기준이다."""

    buff_label: str
    # "버프_패시브"/"버프" 시트의 value(value_type=퍼센트)에서 온다.
    reflect_percent: int

    _PHYSICAL_REDUCTION_PERCENT: ClassVar[int] = 80

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.POST

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        data_list = calculator.data_by_effect[effect_seq_number].damage_data_list
        targeted = [d for d in data_list if d.base.target_id == holder]
        if not targeted:
            return

        reflected: list[DamageCalculateData] = []
        for damage_calc in targeted:
            attacker_id = damage_calc.base.attacker_id
            attacker = calculator.context.characters.get(attacker_id)
            is_magic_attack = (
                damage_calc.base.is_magic_attack
                if damage_calc.base.is_magic_attack is not None
                else (attacker.status.is_magic_attacker if attacker else False)
            )

            # 반사량은 이 버프의 경감/무효화를 적용하기 전 원래 대미지 기준이어야
            # 한다. STAT_ATK_ROLL처럼 매 get_value() 호출마다 다시 굴리는 값
            # 소스를 그대로 두면, 이후 실제 적용 시점(_process_damage 세 번째
            # 순회)에 다시 굴려 반사량과 실제 받는 대미지가 서로 다른 굴림
            # 결과를 쓰게 된다. 여기서 한 번만 굴려 damage_calc.base에
            # 캐싱해 이후 재계산에도 같은 값을 공유하게 한다
            # (buff_companion_guardian.py와 동일한 패턴).
            resolved_value = replace(
                damage_calc.base.value,
                value=damage_calc.base.value.get_value(
                    attacker_id, holder, calculator, effect_seq_number
                ),
            )
            damage_calc.base = replace(damage_calc.base, value=resolved_value)

            pre_reduction_calc = ValueWithModifiers(
                damage_calc.base.value,
                damage_calc.given_modifiers,
                damage_calc.received_modifiers,
            )
            pre_reduction_value = pre_reduction_calc.get_value(
                calculator, attacker_id, holder, effect_seq_number
            )

            if is_magic_attack:
                data_list.remove(damage_calc)
                calculator.data_by_effect[
                    effect_seq_number
                ].nullified_effect_list.append(
                    (holder, f"[{self.buff_label}] 마법 공격 무효화")
                )
            else:
                damage_calc.received_modifiers.append(
                    FloatValueModifier(
                        source_name=self.buff_label,
                        value=-self._PHYSICAL_REDUCTION_PERCENT,
                        applies_to_fixed=True,
                    )
                )

            if attacker_id not in calculator.context.characters:
                continue

            reflect_value = math.floor(pre_reduction_value * self.reflect_percent / 100)
            if reflect_value <= 0:
                continue

            pre_reduction_display = pre_reduction_calc.format_calculation() or str(
                pre_reduction_value
            )
            reflected.append(
                DamageCalculateData(
                    base=DamageData(
                        attacker_id=holder,
                        target_id=attacker_id,
                        value=BaseValueIndicator(
                            value_source=ValueSourceType.FIXED, value=reflect_value
                        ),
                        source_label=f"{self.buff_label}: {holder.name}",
                    ),
                    roll_display=(
                        f"{pre_reduction_display} × "
                        f"{self.reflect_percent / 100:g}[반사 계수]"
                    ),
                )
            )

        data_list.extend(reflected)


class BuffGuardReflect(BuffBase):
    """물리 대미지 80% 경감 + 마법 대미지 무효화 + 경감 전 원래 대미지의
    value% 반사. 반사 배율은 "버프"/"버프_패시브" 시트의 value 컬럼(반드시
    value_type=퍼센트)으로 관리한다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> GuardReflectEvent:
        if self.value_type != ValueType.PERCENT:
            raise ValueError(self.value_type)
        return GuardReflectEvent(
            condition=self.condition,
            buff_label=self.display_id_label(),
            reflect_percent=self.value,
        )
