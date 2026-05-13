from typing import TYPE_CHECKING

from battle.core.commands.models import CommandPart
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import CharacterId, FloatValueModifier

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def get_total_cost(
    parts: list[CommandPart], user: CharacterId, context: "BattlefieldContext"
) -> int:
    user_pos = context.find_character_position(user)
    assert user_pos is not None
    return sum(_get_part_cost(part, user_pos) for part in parts)


def _get_part_cost(part: CommandPart, user_pos: BattlefieldColumnIndex) -> int:
    if part.type_ == ActionType.MOVE and part.targets is not None:
        assert len(part.targets) == 1 and isinstance(
            part.targets[0], BattlefieldColumnIndex
        )
        return abs(part.targets[0].value - user_pos.value)
    elif part.type_ == ActionType.ATTACK:
        return 1
    elif part.type_ == ActionType.SKILL_1:
        return 2
    elif part.type_ == ActionType.SKILL_2:
        return 3
    elif part.type_ == ActionType.USE_ITEM:
        return 1
    elif part.type_ == ActionType.ADMIN:
        return 0
    else:
        raise ValueError(part.type_)
