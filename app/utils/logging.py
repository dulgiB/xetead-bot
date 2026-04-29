import math

from battle.objects.models import CharacterId, ValueWithModifiers


def print_apply_damage(
    attacker_id: CharacterId,
    target_id: CharacterId,
    damage_value: ValueWithModifiers,
    final_value: int,
) -> None:
    print(
        f"[apply_damage] {attacker_id} > {target_id} | {value_with_modifiers_to_str(damage_value)} → -{final_value}"
    )


def print_apply_heal(
    healer_id: CharacterId,
    target_id: CharacterId,
    heal_value: ValueWithModifiers,
    final_value: int,
) -> None:
    print(
        f"[apply_heal] {healer_id} > {target_id} | {value_with_modifiers_to_str(heal_value)} → +{final_value}"
    )


def value_with_modifiers_to_str(value: ValueWithModifiers) -> str:
    result_str = ""
    if value.roll_result:
        result_str += f"({value.roll_result.bonus} + {
            '+'.join(str(roll) for roll in value.roll_result.rolls)
        })"
    else:
        result_str += str(value.base_value)

    if value.int_modifiers:
        result_str += " + ("
        for modifier in value.int_modifiers:
            result_str += f"{'' if modifier.value < 0 else '+'}{modifier.value}[{modifier.source_name}]"
        result_str += ")"
    if value.float_modifiers:
        result_str += " * ("
        for modifier in value.float_modifiers:
            result_str += f"{'' if modifier.value < 0 else '+'}{math.floor(modifier.value * 100)}%[{modifier.source_name}]"
        result_str += ")"
    return result_str
