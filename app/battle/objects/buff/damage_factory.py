from typing import Optional

from battle.core.commands.models import DamageCalculateData
from battle.objects.define import ValueSourceType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    DamageData,
    FloatValueModifier,
)


def make_coefficient_damage_calc(
    attacker_id: CharacterId,
    target_id: CharacterId,
    value_source: ValueSourceType,
    source_name: str,
    coefficient_value: float,
    *,
    consumed_buff_id: Optional[str] = None,
    display_factors: Optional[tuple[tuple[str, float], ...]] = None,
    is_magic_attack: Optional[bool] = None,
    triggers_given_damage_passives: bool = True,
    source_label: Optional[str] = None,
) -> DamageCalculateData:
    """value_source × coefficient_value% 형태의 대미지 항목 하나를 만든다.
    반격/추가 대미지 계열 버프(BuffCounterDamageOn*, BuffCompanionGuardian,
    BuffBonusDamageOnHit, BuffDamageOverTimePerReferencedBuffStack)가
    공유하던 DamageCalculateData/DamageData/BaseValueIndicator/
    FloatValueModifier 조립 코드를 모아둔 것이다.

    FIXED 값 대미지(계수가 아닌 고정 수치)나 roll_display를 직접 지정해야
    하는 경우(BuffReflect 등)는 이 팩토리의 형태에 맞지 않으므로 그대로
    직접 조립한다.

    source_label을 넘기면 답글 요약에도 "[source_label]"로 발생 원인이
    표시된다(계산식 전용인 source_name과 별개) — attacker_id가 원래 커맨드의
    행위자가 아니라 반응형 버프 보유자인 경우(반격류)에만 넘긴다."""
    return DamageCalculateData(
        base=DamageData(
            attacker_id=attacker_id,
            target_id=target_id,
            value=BaseValueIndicator(
                value_source=value_source,
                coefficient=FloatValueModifier(
                    source_name=source_name,
                    value=coefficient_value,
                    display_factors=display_factors,
                ),
                consumed_buff_id=consumed_buff_id,
            ),
            is_magic_attack=is_magic_attack,
            triggers_given_damage_passives=triggers_given_damage_passives,
            source_label=source_label,
        )
    )
