from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

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

    if target_type == PassiveSkillTargetType.SELF_AND_SAME_COLUMN_ALLIES:
        holder_pos = context.find_character_position(holder)
        return [
            char_id
            for char_id, char in context.characters.items()
            if char.faction == holder_char.faction
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
    # buff_mod_event와 effects는 실제 공격에 반영되려면 서로 다른
    # BuffApplyTiming(ON_ACTION vs trigger 기반)이 필요해, PassiveSkillWrapperBuff
    # 하나가 아니라 역할별로 나뉜 버프 인스턴스 각각에 대응한다.
    role: Literal["buff_mod", "effects"]

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
        if self.role == "buff_mod":
            assert self.passive_data.buff_mod_event is not None
            self.passive_data.buff_mod_event.apply(
                holder, attacker_or_target, calculator, effect_seq_number
            )
            return

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

    buff_mod_event(버프 모디파이어 경로)와 effects는 실제로 적용되려면 서로
    다른 BuffApplyTiming이 필요하다: buff_mod_event(예: BuffReceivedDamage)는
    _apply_buff_events()가 실제 공격을 처리하는 시점(ON_ACTION)에 선택돼야만
    damage_data_list에 수정자를 주입할 수 있는 반면, effects는 trigger가
    선언한 타이밍(라운드 시작, 적 후행 시 등)에 반응해야 한다. 두 요구가
    충돌할 수 있으므로(예: trigger='적 후행 시'인데 buff_mod는 ON_ACTION이
    필요) 하나의 PassiveSkillData가 buff_mod_event와 effects를 모두 가지면
    `create()`가 역할별로 나뉜 버프 인스턴스 여러 개를 반환한다.
    """

    @classmethod
    def create(
        cls, holder: CharacterId, passive_data: PassiveSkillData
    ) -> list["PassiveSkillWrapperBuff"]:
        wrappers: list["PassiveSkillWrapperBuff"] = []
        if passive_data.buff_mod_event is not None:
            wrappers.append(cls._create_one(holder, passive_data, "buff_mod"))
        if passive_data.effects:
            wrappers.append(cls._create_one(holder, passive_data, "effects"))
        return wrappers

    @classmethod
    def _create_one(
        cls,
        holder: CharacterId,
        passive_data: PassiveSkillData,
        role: Literal["buff_mod", "effects"],
    ) -> "PassiveSkillWrapperBuff":
        obj: "PassiveSkillWrapperBuff" = object.__new__(cls)
        obj.id = passive_data.id
        obj.uid = BuffUid(holder, holder, f"__passive__{passive_data.id}__{role}")
        obj.given_by = holder
        obj.applied_to = holder
        obj.value = 0
        obj.value_type = None
        obj.duration = BuffDurationCounter(None, None, None)
        # "effects" 역할의 게이팅은 passive_data.effects 각각의 condition으로
        # 처리된다(obj.condition은 쓰이지 않음). "buff_mod" 역할은 apply()가
        # buff_mod_event.apply()로 직접 위임하며 그 안에서는 조건을 다시
        # 확인하지 않으므로, buff_mod_event.condition을 여기 그대로 실어야
        # _apply_buff_events()의 is_applied() 게이팅이 실제로 동작한다.
        obj.condition = (
            passive_data.buff_mod_event.condition
            if role == "buff_mod" and passive_data.buff_mod_event is not None
            else None
        )
        obj.is_debuff = False
        obj._passive_data = passive_data
        obj._role = role
        return obj

    @property
    def timing(self) -> BuffApplyTiming:
        if self._role == "buff_mod":
            # buff_mod_event(ReceivedDamageModEvent 등)는 실제 공격 처리 중
            # _apply_buff_events()가 ON_ACTION 타이밍 버프만 조회하므로, trigger가
            # 무엇이든 항상 ON_ACTION이어야 실제로 대미지/회복에 반영된다.
            return BuffApplyTiming.ON_ACTION
        if self._passive_data.trigger == PassiveSkillTrigger.ROUND_START:
            return BuffApplyTiming.ON_ROUND_START
        if self._passive_data.trigger == PassiveSkillTrigger.ROUND_END:
            return BuffApplyTiming.ON_ROUND_END
        if self._passive_data.trigger == PassiveSkillTrigger.ON_ENEMY_MOVE:
            return BuffApplyTiming.ON_ENEMY_MOVE
        if self._passive_data.trigger == PassiveSkillTrigger.ENEMY_POST_ACTION:
            if any(
                effect.condition is not None
                and effect.condition.requires_round_resolved
                for effect in self._passive_data.effects
            ):
                return BuffApplyTiming.ON_ENEMY_POST_ACTION_RESOLVED
            return BuffApplyTiming.ON_ENEMY_POST_ACTION
        if self._passive_data.trigger == PassiveSkillTrigger.ALLY_DAMAGED:
            return BuffApplyTiming.ALLY_DAMAGED
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> PassiveSkillWrapperEvent:
        return PassiveSkillWrapperEvent(
            condition=self.condition,
            passive_data=self._passive_data,
            role=self._role,
        )
