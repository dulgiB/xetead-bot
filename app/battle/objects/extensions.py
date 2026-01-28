from battle.objects.define import ActionType, ElementType
from battle.objects.models import FloatValueModifier


def get_bonus_damage(
    element: ElementType, attacker_element: ElementType
) -> FloatValueModifier:
    if (
        (element == ElementType.FATE and attacker_element == ElementType.RESIST)
        or (element == ElementType.RESIST and attacker_element == ElementType.EXPLORE)
        or (element == ElementType.EXPLORE and attacker_element == ElementType.CONNECT)
        or (element == ElementType.CONNECT and attacker_element == ElementType.FATE)
    ):
        return FloatValueModifier(0.1)
    return FloatValueModifier(0)


def to_cost(action_type: ActionType) -> int:
    if action_type == ActionType.ATTACK:
        return 1
    elif action_type == ActionType.SKILL_1:
        return 2
    elif action_type == ActionType.SKILL_2:
        return 3
    elif action_type == ActionType.SKILL_3:
        return 4
    elif action_type == ActionType.USE_ITEM:
        return 1
    else:
        raise ValueError(action_type)
