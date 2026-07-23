from typing import TYPE_CHECKING, Optional

from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def is_companion_alive(
    context: "BattlefieldContext", companion_id: Optional[CharacterId]
) -> bool:
    """동료가 전장에 존재하고 체력이 1 이상 남아 있을 때 True. companion_id가
    None이면(즉 아직 한 번도 소환된 적 없으면) False.

    이 저장소는 체력 0인 캐릭터를 자동으로 필드에서 제거하지 않으므로(수동
    제거가 기본), 존재 여부만으로는 "동료가 아직 보호 기능을 제공하는지"를
    판정할 수 없다. curr_hp도 함께 확인해야 전투 대미지로 죽은 동료를 그
    즉시 "부재"로 취급할 수 있다."""
    if companion_id is None:
        return False
    character = context.characters.get(companion_id)
    return character is not None and character.status.curr_hp > 0
