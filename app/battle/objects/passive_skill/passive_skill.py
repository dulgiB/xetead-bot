from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.core.commands.models import DamageCalculateData, HealCalculateData
from battle.objects.buff.buff_base import BuffBase, BuffDurationCounter
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueSourceType
from battle.objects.models import BuffUid, CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.command_calculator import CommandPartCalculator


def _resolve_targets(
    context: "BattlefieldContext",
    holder: CharacterId,
    attacker_or_target: Optional[CharacterId],
    target_type: PassiveSkillTargetType,
) -> list[CharacterId]:
    if target_type == PassiveSkillTargetType.SELF:
        return [holder]

    if target_type == PassiveSkillTargetType.ATTACKER_OR_TARGET:
        return [attacker_or_target] if attacker_or_target else []

    holder_char = context.characters.get(holder)
    if holder_char is None:
        return []

    if target_type == PassiveSkillTargetType.SAME_COLUMN_ALLIES:
        holder_pos = context.find_character_position(holder)
        return [
            char_id
            for char_id, char in context.characters.items()
            if char_id != holder
            and char.faction == holder_char.faction
            and context.find_character_position(char_id) == holder_pos
        ]

    if target_type == PassiveSkillTargetType.ALL_ALLIES:
        return [
            char_id
            for char_id, char in context.characters.items()
            if char.faction == holder_char.faction
        ]

    return []


@dataclass(frozen=True)
class PassiveSkillWrapperEvent(BuffEvent):
    passive_data: PassiveSkillData

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
        # GIVEN_DAMAGE/GIVEN_HEAL 소스 패시브는 해당 타입이 미처리 상태(result_value=None)일 때만 발동.
        # 이미 damage/heal이 모두 처리된 후 _apply_buff_events가 재호출될 때 이중 발동을 방지한다.
        effect_source = self.passive_data.effect.value_source
        effect_data = calculator.data_by_effect[effect_seq_number]
        if effect_source == ValueSourceType.GIVEN_DAMAGE:
            if not any(d.result_value is None for d in effect_data.damage_data_list):
                return
        elif effect_source == ValueSourceType.GIVEN_HEAL:
            if not any(h.result_value is None for h in effect_data.heal_data_list):
                return

        targets = _resolve_targets(
            calculator.context,
            holder,
            attacker_or_target,
            self.passive_data.target_type,
        )
        _, damage_list, heal_list, buff_add_list = self.passive_data.effect.expand(
            calculator.context, holder, targets
        )

        effect_data = calculator.data_by_effect[effect_seq_number]
        for buff_add in buff_add_list:
            calculator.context.buff_container.add(buff_add)
        for damage in damage_list:
            effect_data.damage_data_list.append(DamageCalculateData(damage, []))
        for heal in heal_list:
            effect_data.heal_data_list.append(HealCalculateData(heal, []))


class PassiveSkillWrapperBuff(BuffBase):
    """패시브 스킬을 BuffContainer 내에서 실행하기 위한 래퍼 버프.

    BuffData 없이 직접 생성된다. 플레이어에게는 일반 버프처럼 표시된다.
    """

    @classmethod
    def create(
        cls, holder: CharacterId, passive_data: PassiveSkillData
    ) -> "PassiveSkillWrapperBuff":
        obj: "PassiveSkillWrapperBuff" = object.__new__(cls)
        obj.id = passive_data.id
        obj.uid = BuffUid(holder, holder, f"__passive__{passive_data.id}")
        obj.given_by = holder
        obj.applied_to = holder
        obj.value = 0
        obj.value_type = None
        obj.duration = BuffDurationCounter(None, None, None)
        obj.condition = passive_data.condition
        obj.is_debuff = False
        obj._passive_data = passive_data
        return obj

    @property
    def timing(self) -> BuffApplyTiming:
        if self._passive_data.trigger == PassiveSkillTrigger.ROUND_START:
            return BuffApplyTiming.ON_ROUND_START
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> PassiveSkillWrapperEvent:
        return PassiveSkillWrapperEvent(
            condition=self.condition,
            passive_data=self._passive_data,
        )
