from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar, Optional

from battle.core.commands.models import DamageCalculateData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.buff.damage_factory import make_coefficient_damage_calc
from battle.objects.companion import is_companion_alive
from battle.objects.define import BuffApplyTiming, ValueSourceType
from battle.objects.models import CharacterId, FloatValueModifier

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class CompanionGuardianEvent(BuffEvent):
    """holder(소환자)가 대미지를 받을 때 발동한다. 동료가 살아 있을 때만
    (is_companion_alive) 두 가지 부수 효과를 낸다:
    1) 받는 대미지를 holder/동료가 절반씩(_SPLIT_PERCENT) 나눠 받는다.
    2) 공격자에게 holder의 공격 굴림 _COUNTER_PERCENT%만큼 반격 대미지를 입힌다.
    동료가 없으면 아무 일도 하지 않는다(패시브 설명의 "동료가 필드에 남아
    있는 한"을 그대로 구현)."""

    _SPLIT_PERCENT: ClassVar[int] = 50
    _COUNTER_PERCENT: ClassVar[int] = 80

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
        companion_id = calculator.context.find_companion_id(holder)
        if not is_companion_alive(calculator.context, companion_id):
            return

        effect_data = calculator.data_by_effect[effect_seq_number]
        holder_was_hit = any(
            dc.base.target_id == holder for dc in effect_data.damage_data_list
        )

        # SkillTargetRuleColumn은 동료를 열 대상에 독립적으로 포함시키지
        # 않으므로(항상 holder만 맞은 것으로 취급) 보통은 해당 없지만, 스킬이
        # holder와 동료를 각각 명시적으로 지정하는 등 동료가 같은 effect의
        # 독자적인 대상으로 이미 포함된 예외적인 경우까지 대비해 방어적으로
        # 분담을 건너뛴다 — 그렇지 않으면 동료가 이중으로 얻어맞는다.
        companion_already_targeted = any(
            dc.base.target_id == companion_id for dc in effect_data.damage_data_list
        )
        split_modifier = FloatValueModifier(
            source_name="CompanionBuff1", value=-self._SPLIT_PERCENT, applies_to_fixed=True
        )
        shared_calcs: list[DamageCalculateData] = []
        if not companion_already_targeted:
            for damage_calc in effect_data.damage_data_list:
                if damage_calc.base.target_id != holder:
                    continue
                damage_calc.received_modifiers.append(split_modifier)
                shared_calcs.append(
                    DamageCalculateData(
                        base=replace(damage_calc.base, target_id=companion_id),
                        given_modifiers=list(damage_calc.given_modifiers),
                        received_modifiers=[split_modifier],
                    )
                )
            effect_data.damage_data_list.extend(shared_calcs)

        # holder_was_hit이 False면 이번 발동은 holder가 공격자 쪽(ON_ATTACK)이라
        # _apply_buff_events가 호출한 것이지 실제로 피격당한 게 아니다 — 이 경우
        # attacker_or_target은 holder가 공격한 대상이지 holder를 공격한 대상이
        # 아니므로 반격을 발동하면 안 된다.
        attacker_alive = (
            holder_was_hit
            and attacker_or_target is not None
            and attacker_or_target in calculator.context.characters
        )
        if attacker_alive:
            effect_data.damage_data_list.append(
                make_coefficient_damage_calc(
                    attacker_id=holder,
                    target_id=attacker_or_target,
                    value_source=ValueSourceType.STAT_ATK_ROLL,
                    source_name="CompanionBuff1(반격)",
                    coefficient_value=self._COUNTER_PERCENT,
                )
            )


class BuffCompanionGuardian(BuffBase):
    """CompanionBuff1: 동료가 필드에 살아 있는 한, 받는 대미지를 동료와 절반씩 나누고
    자신을 공격한 대상에게 반격 대미지를 입힌다. 전투 시작 시 1회 부여되는
    영구(패시브) 버프 — 지속시간이 없으므로 duration_turn_value/
    duration_count_value를 비워 등록한다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> BuffEvent:
        return CompanionGuardianEvent(condition=self.condition)
