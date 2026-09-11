from typing import TYPE_CHECKING, cast

from battle.core.commands.models import CommandPart
from battle.objects.define import (
    REVIVAL_COUNT_FOR_EXTRA_COST,
    ActionType,
    BattlefieldColumnIndex,
)
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def get_total_cost(
    parts: list[CommandPart], user: CharacterId, context: "BattlefieldContext"
) -> int:
    user_pos = context.find_character_position(user)
    assert user_pos is not None
    # 총합이 아니라 파트 단위로 얹는다 — 한 커맨드에서 이동을 여러 번 나눠
    # 선언하면 이동 파트마다 중복 적용되는 것이 의도다.
    extra_move_cost = (
        1
        if context.characters[user].status.revival_count >= REVIVAL_COUNT_FOR_EXTRA_COST
        else 0
    )
    total = 0
    for part in parts:
        total += _get_part_cost(part, user_pos, context, extra_move_cost)
        # 뒤따르는 파트의 코스트는 이 이동이 적용된 뒤의 위치를 기준으로 삼는다 —
        # 실제 적용과 사거리 검증도 같은 순차 갱신 방식이다.
        if part.type_ == ActionType.MOVE and part.targets is not None:
            user_pos = cast(BattlefieldColumnIndex, part.targets[0])
    return total


def _get_part_cost(
    part: CommandPart,
    user_pos: BattlefieldColumnIndex,
    context: "BattlefieldContext",
    extra_move_cost: int = 0,
) -> int:
    if part.type_ == ActionType.MOVE and part.targets is not None:
        assert len(part.targets) == 1 and isinstance(
            part.targets[0], BattlefieldColumnIndex
        )
        return abs(part.targets[0].value - user_pos.value) + extra_move_cost
    elif part.type_ == ActionType.ATTACK:
        return 1
    elif part.type_ == ActionType.SKILL and part.skill_id is not None:
        return context.get_skill_data_by_id(part.skill_id).cost
    elif part.type_ == ActionType.USE_ITEM and part.item_id is not None:
        return context.get_item_data_by_id(part.item_id).cost
    elif part.type_ == ActionType.ADMIN:
        return 0
    else:
        raise ValueError(part.type_)
