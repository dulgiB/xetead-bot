import dataclasses

from spreadsheets.models.battle import CharacterDataFromSpreadsheet

from battle.core.battlefield_context import BattlefieldContext
from battle.objects.character.combat_character import CombatCharacter
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.objects.buff.models import BuffData
from battle.objects.skill.models import SkillData
from battle.practice.define import SideType

# SideType ↔ FactionType 내부 매핑
# BattlefieldContext의 position_map·CombatCharacter.faction은 FactionType을 사용하므로
# 내부적으로는 FactionType으로 동작하고, 외부 API에서만 SideType을 노출한다.
_SIDE_TO_FACTION: dict[SideType, FactionType] = {
    SideType.SIDE_1: FactionType.ALLY,
    SideType.SIDE_2: FactionType.ENEMY,
}
_FACTION_TO_SIDE: dict[FactionType, SideType] = {
    FactionType.ALLY: SideType.SIDE_1,
    FactionType.ENEMY: SideType.SIDE_2,
}


class PracticeBattlefieldContext(BattlefieldContext):
    """
    대련 전용 전장 컨텍스트.
    - 캐릭터 체력은 실제 max_hp의 절반으로 초기화된다.
    - 아군/적군 구분 대신 SIDE_1/SIDE_2를 사용한다 (내부적으로는 ALLY/ENEMY에 매핑).
    """

    def __init__(self, buff_dict: dict[str, BuffData], skill_dict: dict[str, SkillData]):
        # 대련에는 milestone_n이 의미 없으므로 고정
        super().__init__(buff_dict, skill_dict, milestone_n=1)

    # ------------------------------------------------------------------
    # 공개 API (SideType 기반)
    # ------------------------------------------------------------------

    def add_character(  # type: ignore[override]
        self,
        data: CharacterDataFromSpreadsheet,
        side: SideType,
        column_idx: BattlefieldColumnIndex,
    ) -> None:
        practice_hp = data.max_hp // 2
        practice_data = dataclasses.replace(data, max_hp=practice_hp, curr_hp=practice_hp)
        super().add_character(practice_data, _SIDE_TO_FACTION[side], column_idx)

    def get_side(self, char_id: CharacterId) -> SideType:
        return _FACTION_TO_SIDE[self.characters[char_id].faction]

    def get_side_characters(self, side: SideType) -> list[CombatCharacter]:
        faction = _SIDE_TO_FACTION[side]
        return [c for c in self.characters.values() if c.faction == faction]
