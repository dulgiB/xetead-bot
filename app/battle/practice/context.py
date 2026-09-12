import dataclasses

from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet

from battle.core.battlefield_context import BattlefieldContext
from battle.objects.buff.models import BuffData
from battle.objects.character.combat_character import CombatCharacter
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.models import SkillData
from battle.practice.define import SideType

# 내부는 상위 클래스와 같은 FactionType으로 동작하고, 외부 API에서만
# SideType을 노출한다.
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
    - `is_duel`로 대련(대등한 PvP)과 상시전투(아군 vs 적군)를 가른다. 진영에
      따라 다르게 동작하는 규칙이 대련에서는 비대칭이 되기 때문이다.
    """

    def __init__(
        self,
        buff_dict: dict[str, BuffData],
        skill_dict: dict[str, SkillData],
        passive_skill_dict: "dict[str, PassiveSkillData] | None" = None,
        item_dict: "dict[str, ItemData] | None" = None,
        *,
        is_duel: bool = True,
    ):
        self.is_duel = is_duel
        # 인벤토리는 미지원이지만 item_dict는 이름 조회용으로 받아 둔다 —
        # 파서가 "여기선 못 쓰는 아이템"과 "등록되지 않은 이름"을 구분해
        # 정확한 에러를 낼 수 있어야 하기 때문이다.
        super().__init__(
            buff_dict,
            skill_dict,
            passive_skill_dict=passive_skill_dict,
            item_dict=item_dict,
            milestone_n=1,
        )

    @property
    def allow_item_usage(self) -> bool:
        return False

    @property
    def allow_fate_intervention(self) -> bool:
        return False

    def _remove_eliminated_characters(self):
        """대련에서는 0 체력 자동 탈락을 양 팀 모두 적용하지 않는다.

        기반 구현은 FactionType.ENEMY만 제거하는데(아군은 admin이
        `[탈락/이름]`으로 직접 처리), 대련에서는 그게 곧 "2팀만 제거된다"는
        뜻이 된다. 그러면 2팀 전사자는 체력 비율 계산의 분자·분모에서 함께
        빠지고 1팀 전사자는 0/최대로 남아, 양 팀이 똑같이 한 명씩 잃어도
        2팀이 이긴다. 대련 참가자는 자진 기권(`[탈락]`)으로 직접 물러날 수
        있으므로, 자동 제거는 양쪽 모두 하지 않는 쪽으로 맞춘다."""
        if self.is_duel:
            return []
        return super()._remove_eliminated_characters()

    # ------------------------------------------------------------------
    # 공개 API (SideType 기반)
    # ------------------------------------------------------------------

    def add_character(  # type: ignore[override]
        self,
        data: CombatCharacterDataFromSpreadsheet,
        side: SideType,
        column_idx: BattlefieldColumnIndex,
    ) -> None:
        practice_hp = data.max_hp // 2
        practice_data = dataclasses.replace(
            data, max_hp=practice_hp, curr_hp=practice_hp
        )
        super().add_character(practice_data, _SIDE_TO_FACTION[side], column_idx)

    def get_side(self, char_id: CharacterId) -> SideType:
        return _FACTION_TO_SIDE[self.characters[char_id].faction]

    def get_side_characters(self, side: SideType) -> list[CombatCharacter]:
        faction = _SIDE_TO_FACTION[side]
        return [c for c in self.characters.values() if c.faction == faction]
