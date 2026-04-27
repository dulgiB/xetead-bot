from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import ActionCommand, CommandBase, MoveCommand
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


def to_cost(command: CommandBase, context: BattlefieldContext) -> int:
    if isinstance(command, MoveCommand):
        user_pos = context.find_character_position(command.user)
        if user_pos:
            return abs(user_pos.value - command.to_position.value)

    # TODO: MoveCommand를 따로 쓰면 ActionType.MOVE 가 애매함
    elif isinstance(command, ActionCommand):
        if command.type_ == ActionType.ATTACK:
            return 1
        elif command.type_ == ActionType.SKILL_1:
            return 2
        elif command.type_ == ActionType.SKILL_2:
            return 3
        elif command.type_ == ActionType.USE_ITEM:
            return 1
        else:
            raise ValueError(command.type_)

    return 0
