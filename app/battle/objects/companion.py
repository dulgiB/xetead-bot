from typing import TYPE_CHECKING, Optional

from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def is_companion_alive(
    context: "BattlefieldContext", companion_id: Optional[CharacterId]
) -> bool:
    """동료가 전장에 존재하고 체력이 1 이상 남아 있을 때 True. companion_id가
    None이면(즉 아직 한 번도 소환된 적 없으면) False.

    체력이 0이 된 동료도 필드에 남아 있으므로, curr_hp까지 확인해야 전투
    대미지로 죽은 동료를 그 즉시 "부재"로 취급할 수 있다."""
    if companion_id is None:
        return False
    character = context.characters.get(companion_id)
    return character is not None and character.status.curr_hp > 0
