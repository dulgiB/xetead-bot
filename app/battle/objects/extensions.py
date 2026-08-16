from typing import TYPE_CHECKING, cast

from battle.core.commands.models import CommandPart
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def get_total_cost(
    parts: list[CommandPart], user: CharacterId, context: "BattlefieldContext"
) -> int:
    user_pos = context.find_character_position(user)
    assert user_pos is not None
    total = 0
    for part in parts:
        total += _get_part_cost(part, user_pos, context)
        # 같은 커맨드 안에 이동이 여러 번 나뉘어 있으면, 그다음 파트(이동 포함)의
        # 코스트는 원래 위치가 아니라 이 이동이 적용된 뒤의 위치를 기준으로
        # 계산해야 한다 — 실제 적용(command_calculator._process_move)과 사거리
        # 검증(command_processors.py)이 이미 순차 갱신 방식이므로 코스트도 맞춰야 한다.
        if part.type_ == ActionType.MOVE and part.targets is not None:
            user_pos = cast(BattlefieldColumnIndex, part.targets[0])
    return total


def _get_part_cost(
    part: CommandPart, user_pos: BattlefieldColumnIndex, context: "BattlefieldContext"
) -> int:
    if part.type_ == ActionType.MOVE and part.targets is not None:
        assert len(part.targets) == 1 and isinstance(
            part.targets[0], BattlefieldColumnIndex
        )
        return abs(part.targets[0].value - user_pos.value)
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
