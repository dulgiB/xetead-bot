from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

from battle.core.commands.models import DamageCalculateData, HealCalculateData
from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, ValueSourceType
from battle.objects.models import BuffUid, CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.models import SkillEffectBase

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
            and char_id not in context.companion_owners
            and char.faction == holder_char.faction
            and context.find_character_position(char_id) == holder_pos
        ]

    if target_type == PassiveSkillTargetType.SELF_AND_SAME_COLUMN_ALLIES:
        holder_pos = context.find_character_position(holder)
        return [
            char_id
            for char_id, char in context.characters.items()
            if char_id not in context.companion_owners
            and char.faction == holder_char.faction
            and context.find_character_position(char_id) == holder_pos
        ]

    if target_type == PassiveSkillTargetType.SELF_AND_ADJACENT_COLUMN_ALLIES:
        holder_column = context.find_character_position(holder).value
        return [
            char_id
            for char_id, char in context.characters.items()
            if char_id not in context.companion_owners
            and char.faction == holder_char.faction
            and abs(context.find_character_position(char_id).value - holder_column) <= 1
        ]

    if target_type == PassiveSkillTargetType.ALL_ALLIES:
        return [
            char_id
            for char_id, char in context.characters.items()
            if char_id not in context.companion_owners
            and char.faction == holder_char.faction
        ]

    if target_type == PassiveSkillTargetType.LOWEST_HP_ALLY:
        allies = [
            char_id
            for char_id, char in context.characters.items()
            if char_id not in context.companion_owners
            and char.faction == holder_char.faction
        ]
        if not allies:
            return []
        return [min(allies, key=lambda cid: context.characters[cid].status.curr_hp)]

    return []


PassiveSkillWrapperRole = Literal["buff_mod", "effects", "effects_resolved"]


def _needs_round_resolved(effect: SkillEffectBase) -> bool:
    """이 효과가 "이번 라운드의 피격이 모두 확정된 뒤"에만 올바른 값을 내는지.
    효과 본체가 damaged_this_round를 직접 읽거나(requires_round_resolved),
    그런 조건(RoundResolvedCondition)을 달고 있으면 True."""
    if effect.requires_round_resolved:
        return True
    condition = effect.condition
    return condition is not None and condition.requires_round_resolved


def _indexed_effects_for_role(
    passive_data: PassiveSkillData, role: PassiveSkillWrapperRole
) -> list[tuple[int, SkillEffectBase]]:
    """effects를 평가 시점별로 나눈다. 인덱스는 원본 effects 기준을 유지한다 —
    apply()가 _fired_given_value_passives 키로 쓰기 때문에 역할별로 다시
    매기면 서로 다른 효과가 같은 키를 공유하게 된다."""
    want_resolved = role == "effects_resolved"
    return [
        (i, effect)
        for i, effect in enumerate(passive_data.effects)
        if _needs_round_resolved(effect) == want_resolved
    ]


@dataclass(frozen=True)
class PassiveSkillWrapperEvent(BuffEvent):
    passive_data: PassiveSkillData
    # buff_mod_event와 effects는 필요한 BuffApplyTiming이 서로 달라 버프
    # 인스턴스를 역할별로 나눠 등록한다. effects도 라운드 확정 전/후로
    # 평가 시점이 갈려 effects/effects_resolved로 한 번 더 나뉜다.
    role: PassiveSkillWrapperRole

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
            # buff_mod은 상대가 있는 타이밍으로만 등록된다.
            assert attacker_or_target is not None
            self.passive_data.buff_mod_event.apply(
                holder, attacker_or_target, calculator, effect_seq_number
            )
            return

        effect_data = calculator.data_by_effect[effect_seq_number]
        for i, effect in _indexed_effects_for_role(self.passive_data, self.role):
            condition = effect.condition
            if condition is not None and not condition.is_applied(
                calculator.context, holder, attacker_or_target
            ):
                continue

            # holder가 같은 effect에서 공격자이자 대상이면(자기 포함 광역기 등)
            # _apply_buff_events가 이 이벤트를 두 번 부르므로 1회로 묶는다.
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
                effect_data.damage_data_list.append(DamageCalculateData(damage))
            for heal in heal_list:
                effect_data.heal_data_list.append(HealCalculateData(heal))


# buff_mod 역할이 ON_ACTION 대신 반응형 타이밍으로 등록돼야 하는 트리거들.
# 새 반응형 트리거를 추가하면 여기도 갱신해야 한다 — 빠지면 그 조합의
# 패시브가 ON_ACTION 조회에 걸리지 않아 조용히 발동하지 않는다.
_REACTIVE_TRIGGER_TIMING: dict[PassiveSkillTrigger, BuffApplyTiming] = {
    PassiveSkillTrigger.ON_ENEMY_MOVE: BuffApplyTiming.ON_ENEMY_MOVE,
    PassiveSkillTrigger.ALLY_DAMAGED: BuffApplyTiming.ALLY_DAMAGED,
    PassiveSkillTrigger.ALLY_IN_RANGE_DAMAGED: BuffApplyTiming.ALLY_IN_RANGE_DAMAGED,
}


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

    effects끼리도 같은 이유로 한 번 더 갈린다: damaged_this_round를 읽는 효과는
    적의 공격이 모두 반영된 뒤(ON_ENEMY_POST_ACTION_RESOLVED)에 평가돼야 하지만,
    그 라운드의 피격을 실제로 경감해 줄 버프를 부여하는 효과는 그 전
    (ON_ENEMY_POST_ACTION)에 걸려야 한다. 그래서 effects/effects_resolved로
    나눠 각각 등록한다 — 한쪽에 맞추면 다른 쪽이 한 라운드씩 밀린다.
    """

    _passive_data: PassiveSkillData
    _role: PassiveSkillWrapperRole

    @classmethod
    def create(
        cls, holder: CharacterId, passive_data: PassiveSkillData
    ) -> list["PassiveSkillWrapperBuff"]:
        wrappers: list["PassiveSkillWrapperBuff"] = []
        if passive_data.buff_mod_event is not None:
            wrappers.append(cls._create_one(holder, passive_data, "buff_mod"))
        for role in ("effects", "effects_resolved"):
            if _indexed_effects_for_role(passive_data, role):
                wrappers.append(cls._create_one(holder, passive_data, role))
        return wrappers

    @classmethod
    def _create_one(
        cls,
        holder: CharacterId,
        passive_data: PassiveSkillData,
        role: PassiveSkillWrapperRole,
    ) -> "PassiveSkillWrapperBuff":
        # "effects" 역할은 각 effect의 condition이 게이팅하므로 비워 둔다.
        # "buff_mod"은 apply()가 조건을 다시 보지 않고 위임하므로, 여기에
        # 실어야 _apply_buff_events()의 게이팅이 동작한다.
        condition = (
            passive_data.buff_mod_event.condition
            if role == "buff_mod" and passive_data.buff_mod_event is not None
            else None
        )
        obj = cls._create_bare(
            id_=passive_data.id,
            uid=BuffUid(holder, holder, f"__passive__{passive_data.id}__{role}"),
            given_by=holder,
            applied_to=holder,
            condition=condition,
        )
        obj._passive_data = passive_data
        obj._role = role
        return obj

    def get_description(self, context: "BattlefieldContext") -> str:
        """패시브 스킬은 "버프" 시트가 아니라 "스킬_패시브" 시트에서 온
        데이터라 context.get_buff_data_by_id(self.id)로 조회할 수 없다
        (KeyError) — 이미 들고 있는 PassiveSkillData의 설명을 그대로 쓴다."""
        return self._passive_data.description

    @property
    def timing(self) -> BuffApplyTiming:
        if self._role == "buff_mod":
            # 수치를 바꾸려면 실제 공격 처리 중이어야 해서 기본은 ON_ACTION이다.
            # 다만 제3자 반응형 트리거는 _apply_buff_events가 아예 호출되지
            # 않으므로 BuffContainer.on_*()가 조회하는 타이밍을 대신 쓴다.
            return _REACTIVE_TRIGGER_TIMING.get(
                self._passive_data.trigger, BuffApplyTiming.ON_ACTION
            )
        if self._passive_data.trigger == PassiveSkillTrigger.BATTLE_START:
            return BuffApplyTiming.ON_BATTLE_START
        if self._passive_data.trigger == PassiveSkillTrigger.ROUND_START:
            return BuffApplyTiming.ON_ROUND_START
        if self._passive_data.trigger == PassiveSkillTrigger.ROUND_END:
            return BuffApplyTiming.ON_ROUND_END
        if self._passive_data.trigger == PassiveSkillTrigger.ON_ENEMY_MOVE:
            return BuffApplyTiming.ON_ENEMY_MOVE
        if self._passive_data.trigger == PassiveSkillTrigger.ENEMY_POST_ACTION:
            # _indexed_effects_for_role이 이미 효과를 갈라 놨으므로 역할만 본다.
            if self._role == "effects_resolved":
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
