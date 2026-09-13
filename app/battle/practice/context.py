import dataclasses

from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet

from battle.core.battlefield_context import BattlefieldContext
from battle.objects.buff.models import BuffData
from battle.objects.character.combat_character import CombatCharacter
from battle.objects.define import (
    FATE_INTERVENTION_HP_COST,
    BattlefieldColumnIndex,
    FactionType,
)
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.models import SkillData
from battle.practice.define import PracticeBattleMode, SideType

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


@dataclasses.dataclass
class PersistentHp:
    """캐릭터 시트에 적힌 실제 체력. 임시 체력(전장의 status.curr_hp)과
    구분해서 들고 있는다 — 결투에서 키워드 보정 대가와 패배 대가만 이쪽에서
    빠지기 때문이다."""

    curr_hp: int
    max_hp: int


class PracticeBattlefieldContext(BattlefieldContext):
    """
    대련/상시전투/결투 전용 전장 컨텍스트.
    - 캐릭터 체력은 실제 max_hp의 절반으로 초기화된다 (결투는 max_hp 그대로).
    - 아군/적군 구분 대신 SIDE_1/SIDE_2를 사용한다 (내부적으로는 ALLY/ENEMY에 매핑).
    - `is_duel`로 대등한 PvP(대련·결투)와 상시전투(아군 vs 적군)를 가른다.
      진영에 따라 다르게 동작하는 규칙이 대등한 PvP에서는 비대칭이 되기
      때문이다.
    """

    def __init__(
        self,
        buff_dict: dict[str, BuffData],
        skill_dict: dict[str, SkillData],
        passive_skill_dict: "dict[str, PassiveSkillData] | None" = None,
        item_dict: "dict[str, ItemData] | None" = None,
        *,
        mode: PracticeBattleMode = PracticeBattleMode.PRACTICE,
    ):
        self.mode = mode
        # 결투 한정으로 캐릭터별 실제 체력을 들고 있는다. 필드에서 빠진
        # 캐릭터(자진 기권)의 값도 지우지 않는다 — 패배 대가는 기권자에게도
        # 적용되기 때문이다.
        self.persistent_hp: dict[CharacterId, PersistentHp] = {}
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
    def is_duel(self) -> bool:
        return self.mode != PracticeBattleMode.INVESTIGATION

    @property
    def allow_item_usage(self) -> bool:
        return False

    @property
    def allow_fate_intervention(self) -> bool:
        """결투에서만 허용한다 — 대가를 임시 체력이 아니라 시트의 실제
        체력에서 빼므로(`pay_fate_cost_hp()`), 대련/상시전투를 막는 이유인
        "되돌릴 수 없는 자원을 임시 캐릭터에게 걸 수 없다"가 결투에는
        해당하지 않는다."""
        return self.mode == PracticeBattleMode.DUEL

    def fate_cost_hp(self, character: CombatCharacter) -> int:
        if self.mode != PracticeBattleMode.DUEL:
            return super().fate_cost_hp(character)
        return self.persistent_hp[character.id].curr_hp

    def pay_fate_cost_hp(self, character: CombatCharacter) -> tuple[int, int, bool]:
        if self.mode != PracticeBattleMode.DUEL:
            return super().pay_fate_cost_hp(character)
        # 임시 체력은 그대로 두고 실제 체력만 깎는다. 시트 반영은 봇 계층이
        # 커맨드 처리 성공 후에 이 값을 읽어 수행한다.
        hp = self.persistent_hp[character.id]
        hp.curr_hp -= FATE_INTERVENTION_HP_COST
        return hp.curr_hp, hp.max_hp, True

    def _remove_eliminated_characters(self):
        """대등한 PvP(대련·결투)에서는 0 체력 자동 탈락을 양 팀 모두
        적용하지 않는다.

        기반 구현은 FactionType.ENEMY만 제거하는데(아군은 admin이
        `[탈락/이름]`으로 직접 처리), 여기서는 그게 곧 "2팀만 제거된다"는
        뜻이 된다. 그러면 2팀 전사자는 체력 비율 계산의 분자·분모에서 함께
        빠지고 1팀 전사자는 0/최대로 남아, 양 팀이 똑같이 한 명씩 잃어도
        2팀이 이긴다. 참가자는 자진 기권(`[탈락]`)으로 직접 물러날 수
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
        practice_hp = data.max_hp if self.mode.uses_full_hp else data.max_hp // 2
        practice_data = dataclasses.replace(
            data, max_hp=practice_hp, curr_hp=practice_hp
        )
        super().add_character(practice_data, _SIDE_TO_FACTION[side], column_idx)
        if self.mode == PracticeBattleMode.DUEL:
            self.persistent_hp[CharacterId(data.name)] = PersistentHp(
                curr_hp=data.curr_hp if data.curr_hp is not None else data.max_hp,
                max_hp=data.max_hp,
            )

    def get_side(self, char_id: CharacterId) -> SideType:
        return _FACTION_TO_SIDE[self.characters[char_id].faction]

    def get_side_characters(self, side: SideType) -> list[CombatCharacter]:
        faction = _SIDE_TO_FACTION[side]
        return [c for c in self.characters.values() if c.faction == faction]
