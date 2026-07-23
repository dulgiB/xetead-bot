from typing import TYPE_CHECKING

from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext

_COMPANION_SUFFIX = "(진짜)"


def companion_id_for(owner_id: CharacterId) -> CharacterId:
    """owner_id의 소환수 동료 캐릭터 id. 이름 규칙만으로 도출되므로, 소환/재소환
    시점이 달라도(즉 서로 다른 CombatCharacter 인스턴스라도) 같은 이름을 쓰는 한
    항상 동일한 CharacterId로 취급된다(CharacterId는 name 기준 동등성 비교)."""
    return CharacterId(f"{owner_id.name}{_COMPANION_SUFFIX}")


def is_companion_alive(context: "BattlefieldContext", companion_id: CharacterId) -> bool:
    """동료가 전장에 존재하고 체력이 1 이상 남아 있을 때 True.

    이 저장소는 체력 0인 캐릭터를 자동으로 필드에서 제거하지 않으므로(수동
    제거가 기본), 존재 여부만으로는 "동료가 아직 보호 기능을 제공하는지"를
    판정할 수 없다. curr_hp도 함께 확인해야 전투 대미지로 죽은 동료를 그
    즉시 "부재"로 취급할 수 있다."""
    character = context.characters.get(companion_id)
    return character is not None and character.status.curr_hp > 0
