import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Optional

from battle.core.commands.models import DamageCalculateData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.buff.damage_factory import make_coefficient_damage_calc
from battle.objects.companion import is_companion_alive
from battle.objects.define import BuffApplyTiming, ValueSourceType, ValueType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    ValueWithModifiers,
)

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class CompanionGuardianEvent(BuffEvent):
    """holder(소환자)가 대미지를 받을 때 발동한다. 동료가 살아 있을 때만
    (is_companion_alive) 두 가지 부수 효과를 낸다:
    1) 받는 대미지를 holder/동료가 split_percent%씩 나눠 받는다.
    2) 공격자에게 holder의 공격 굴림 counter_percent%만큼 반격 대미지를 입힌다.
    동료가 없으면 아무 일도 하지 않는다(패시브 설명의 "동료가 필드에 남아
    있는 한"을 그대로 구현).

    두 비율은 "버프" 시트의 value(분담 비율)/value_2(반격 비율) 컬럼(둘 다
    퍼센트로 해석)에서 온다."""

    split_percent: int
    counter_percent: int

    # 표시용 라벨. 여러 캐릭터가 공유하는 클래스라 이름을 하드코딩하지 않고
    # 이 버프를 등록한 시트 행의 id를 그대로 쓴다.
    label: str

    @property
    def priority(self) -> BuffEventCalculatePriority:
        # POST여야 다른 받는 대미지 버프가 모두 반영된 최종 수치를 기준으로
        # 나눈다. NORMAL이면 경감이 holder 몫에만 적용되는 비대칭이 생긴다.
        return BuffEventCalculatePriority.POST

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: Optional[CharacterId],
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        companion_id = calculator.context.find_companion_id(holder)
        if not is_companion_alive(calculator.context, companion_id):
            return
        assert companion_id is not None  # is_companion_alive()가 이미 보장

        effect_data = calculator.data_by_effect[effect_seq_number]
        holder_was_hit = any(
            dc.base.target_id == holder for dc in effect_data.damage_data_list
        )

        # 스킬이 holder와 동료를 각각 명시적으로 지정하는 등, 동료가 이미
        # 같은 effect의 독자적인 대상이면 분담까지 하면 이중으로 맞는다.
        companion_already_targeted = any(
            dc.base.target_id == companion_id for dc in effect_data.damage_data_list
        )
        shared_calcs: list[DamageCalculateData] = []
        if not companion_already_targeted:
            for damage_calc in effect_data.damage_data_list:
                if damage_calc.base.target_id != holder:
                    continue
                # 최종 수치를 한 번만 확정한 뒤 비율로 갈라 각자 FIXED
                # 대미지로 만든다 — 각자 다시 modifier를 적용하면 증감이
                # 한쪽에만 반영되는 비대칭이 재발한다.
                final_calc = ValueWithModifiers(
                    damage_calc.base.value,
                    damage_calc.given_modifiers,
                    damage_calc.received_modifiers,
                )
                total_value = final_calc.get_value(
                    calculator, damage_calc.base.attacker_id, holder, effect_seq_number
                )
                calc_display = final_calc.format_calculation() or str(total_value)
                companion_share = math.floor(total_value * self.split_percent / 100)
                holder_share = total_value - companion_share

                damage_calc.base = replace(
                    damage_calc.base,
                    value=BaseValueIndicator(
                        value_source=ValueSourceType.FIXED, value=holder_share
                    ),
                )
                damage_calc.given_modifiers = []
                damage_calc.received_modifiers = []
                damage_calc.roll_display = f"{calc_display} × {(100 - self.split_percent) / 100:g}[{self.label}]"
                shared_calcs.append(
                    DamageCalculateData(
                        base=replace(
                            damage_calc.base,
                            target_id=companion_id,
                            value=BaseValueIndicator(
                                value_source=ValueSourceType.FIXED,
                                value=companion_share,
                            ),
                        ),
                        roll_display=(
                            f"{calc_display} × {self.split_percent / 100:g}[{self.label}]"
                        ),
                    )
                )
            effect_data.damage_data_list.extend(shared_calcs)

        # holder_was_hit이 False면 holder는 공격자 쪽이라 attacker_or_target이
        # "holder를 공격한 자"가 아니다 — 반격을 발동하면 안 된다.
        attacker_alive = (
            holder_was_hit
            and attacker_or_target is not None
            and attacker_or_target in calculator.context.characters
        )
        if attacker_alive:
            assert attacker_or_target is not None  # attacker_alive가 이미 보장
            counter_label = f"{self.label}(반격)"
            effect_data.damage_data_list.append(
                make_coefficient_damage_calc(
                    attacker_id=holder,
                    target_id=attacker_or_target,
                    value_source=ValueSourceType.STAT_ATK_ROLL,
                    source_name=counter_label,
                    coefficient_value=self.counter_percent,
                    triggers_received_damage_passives=False,
                    source_label=counter_label,
                )
            )


class BuffCompanionGuardian(BuffBase):
    """CompanionBuff1: 동료가 필드에 살아 있는 한, 받는 대미지를 value%씩
    나누고 자신을 공격한 대상에게 공격 굴림 value_2%만큼 반격 대미지를
    입힌다(둘 다 퍼센트로 해석). 전투 시작 시 1회 부여되는 영구(패시브)
    버프 — 지속시간이 없으므로 duration_turn_value/duration_count_value를
    비워 등록한다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> BuffEvent:
        if self.value_type != ValueType.PERCENT:
            raise ValueError(self.value_type)
        return CompanionGuardianEvent(
            condition=self.condition,
            label=self.display_id_label(),
            split_percent=self.value,
            counter_percent=self.value_2,
        )
