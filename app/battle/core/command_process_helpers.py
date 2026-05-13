from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import BuffApplyTiming, BuffCountDeductCondition
from battle.objects.models import CharacterId, DamageData, HealData, ValueWithModifiers

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.commands.models import CommandPartCalculator


def process_move(
    calculator: "CommandPartCalculator", context: "BattlefieldContext"
) -> None:
    for move_data in calculator.move_list:
        context.move_character_to(move_data.character_id, move_data.to_position)


def process_damage(
    calculator: "CommandPartCalculator", context: "BattlefieldContext"
) -> None:
    for damage_calc in list(calculator.damage_data_list):
        _apply_buff_events(
            calculator,
            context,
            damage_calc.base.attacker_id,
            BuffCountDeductCondition.ON_ATTACK,
            damage_calc.base.target_id,
        )
        _apply_buff_events(
            calculator,
            context,
            damage_calc.base.target_id,
            BuffCountDeductCondition.ON_HIT,
            damage_calc.base.attacker_id,
        )
    for damage_calc in calculator.damage_data_list:
        attacker = context.characters[damage_calc.base.attacker_id]
        target = context.characters[damage_calc.base.target_id]

        if attacker.status.is_magic_attacker:
            damage_calc.modifiers.append(target.status.m_res)

        context.apply_damage(
            damage_calc.base.attacker_id,
            damage_calc.base.target_id,
            ValueWithModifiers(damage_calc.base.value, damage_calc.modifiers),
            calculator,
        )


def process_heal(
    calculator: "CommandPartCalculator", context: "BattlefieldContext"
) -> None:
    for heal_calc in list(calculator.heal_data_list):
        _apply_buff_events(
            calculator,
            context,
            heal_calc.base.healer_id,
            None,
            heal_calc.base.target_id,
        )
        _apply_buff_events(
            calculator,
            context,
            heal_calc.base.target_id,
            None,
            heal_calc.base.healer_id,
        )
    for heal_calc in calculator.heal_data_list:
        context.apply_heal(
            heal_calc.base.healer_id,
            heal_calc.base.target_id,
            ValueWithModifiers(heal_calc.base.value, heal_calc.modifiers),
            calculator,
        )


def process_buff_add(
    context: "BattlefieldContext",
    buff_add_list: list[BuffAddData],
    phase: RoundPhaseType,
    *,
    remaining_parts_dict: Optional[
        dict[CharacterId, list[DamageData | HealData | BuffAddData]]
    ],
    user_id: Optional[CharacterId],
) -> None:
    if phase == RoundPhaseType.ALLY_ACTION or phase == RoundPhaseType.ENEMY_POST_ACTION:
        for data in buff_add_list:
            context.buff_container.add(data)
    elif (
        phase == RoundPhaseType.ENEMY_PRE_ACTION
        and remaining_parts_dict is not None
        and user_id is not None
    ):
        pre_buffs = [buff for buff in buff_add_list if buff.add_timing == phase]
        for data in pre_buffs:
            context.buff_container.add(data)
        post_buffs = [buff for buff in buff_add_list if buff.add_timing == phase]
        for data in post_buffs:
            remaining_parts_dict[user_id].append(data)
    else:
        raise ValueError(f"Cannot add buffs at this phase: {phase}")


def _apply_buff_events(
    calculator: "CommandPartCalculator",
    context: "BattlefieldContext",
    char_id: CharacterId,
    deduct_condition: Optional[BuffCountDeductCondition],
    attacker_or_target: CharacterId = None,
) -> None:
    buffs = context.buff_container.get_buffs_by(char_id, BuffApplyTiming.ON_ACTION)
    if deduct_condition is not None:
        for buff in buffs:
            buff.duration.deduct_count(deduct_condition)
            if buff.duration.finished:
                context.buff_container.remove(buff.uid)

    events = [buff.create_event() for buff in buffs]
    events.sort(key=lambda e: e.priority.value)
    for event in events:
        if event.is_applied(context, char_id, attacker_or_target):
            event.apply(char_id, attacker_or_target, context, calculator)
