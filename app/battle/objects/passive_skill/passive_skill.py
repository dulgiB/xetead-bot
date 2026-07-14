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

    if target_type == PassiveSkillTargetType.LOWEST_HP_ALLY:
        allies = [
            char_id
            for char_id, char in context.characters.items()
            if char.faction == holder_char.faction
        ]
        if not allies:
            return []
        return [min(allies, key=lambda cid: context.characters[cid].status.curr_hp)]

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
        if self.passive_data.buff_mod_event is not None:
            # Buff modifier 경로: 기존 계산에 수정자를 직접 주입. effects 경로와
            # 상호 배타적이지 않으므로 return하지 않고 계속 진행한다.
            self.passive_data.buff_mod_event.apply(
                holder, attacker_or_target, calculator, effect_seq_number
            )

        effect_data = calculator.data_by_effect[effect_seq_number]
        for i, effect in enumerate(self.passive_data.effects):
            condition = effect.condition
            if condition is not None and not condition.is_applied(
                calculator.context, holder, attacker_or_target
            ):
                continue

            # GIVEN_DAMAGE/GIVEN_HEAL 이중 발동 방지. holder가 같은 effect 안에서
            # 공격자이자 대상(자기 포함 광역기 등)이면 _apply_buff_events가 이
            # 이벤트를 두 번(공격자 측, 대상 측) 호출할 수 있으므로,
            # (effect_seq_number, holder, i) 조합당 1회만 발동하도록 기록한다.
            if effect.value_source in (
                ValueSourceType.GIVEN_DAMAGE,
                ValueSourceType.GIVEN_HEAL,
            ):
                key = (effect_seq_number, holder, i)
                if key in calculator._fired_given_value_passives:
                    continue
                calculator._fired_given_value_passives.add(key)

            targets = _resolve_targets(
                calculator.context,
                holder,
                attacker_or_target,
                self.passive_data.target_type,
            )
            _, damage_list, heal_list, buff_add_list, _ = effect.expand(
                calculator.context, holder, targets
            )

            for buff_add in buff_add_list:
                if calculator._buff_add_gate_passes(buff_add, effect_seq_number):
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
        # 게이팅은 이제 passive_data.effects 각각의 condition으로 처리된다.
        obj.condition = None
        obj.is_debuff = False
        obj._passive_data = passive_data
        return obj

    @property
    def timing(self) -> BuffApplyTiming:
        if self._passive_data.trigger == PassiveSkillTrigger.ROUND_START:
            return BuffApplyTiming.ON_ROUND_START
        if self._passive_data.trigger == PassiveSkillTrigger.ON_ENEMY_MOVE:
            return BuffApplyTiming.ON_ENEMY_MOVE
        if self._passive_data.trigger == PassiveSkillTrigger.ENEMY_POST_ACTION:
            return BuffApplyTiming.ON_ENEMY_POST_ACTION
        if self._passive_data.trigger == PassiveSkillTrigger.ALLY_DAMAGED:
            return BuffApplyTiming.ALLY_DAMAGED
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> PassiveSkillWrapperEvent:
        return PassiveSkillWrapperEvent(
            condition=self.condition,
            passive_data=self._passive_data,
        )
