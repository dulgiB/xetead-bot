from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import ActionCommandPart, CommandPartBase
from battle.objects.define import ActionType, ElementType
from battle.objects.models import CharacterId, FloatValueModifier


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


def get_total_cost(
    parts: list[CommandPartBase], user: CharacterId, context: BattlefieldContext
) -> int:
    return sum(_get_part_cost(part, user, context) for part in parts)


def _get_part_cost(
    part: CommandPartBase, user: CharacterId, context: BattlefieldContext
) -> int:
    if isinstance(part, ActionCommandPart):
        if (
            part.type_ == ActionType.MOVE
            and part.target_positions is not None
            and len(part.target_positions) == 1
        ):
            user_pos = context.find_character_position(user)
            if user_pos:
                return abs(part.target_positions[0].value - user_pos.value)
        elif part.type_ == ActionType.ATTACK:
            return 1
        elif part.type_ == ActionType.SKILL_1:
            return 2
        elif part.type_ == ActionType.SKILL_2:
            return 3
        elif part.type_ == ActionType.USE_ITEM:
            return 1
        else:
            raise ValueError(part.type_)

    return 0
