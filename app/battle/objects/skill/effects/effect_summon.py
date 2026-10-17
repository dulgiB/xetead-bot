from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import (
    CharacterId,
    DamageData,
    HealData,
    MoveData,
    SummonData,
)
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectSummon(SkillEffectBase):
    """지정한 열에 필드에 없는 에너미를 시전자의 진영으로 소환한다.

    `SkillTargetRuleSummon`과 함께 쓴다. 소환할 캐릭터는 "에너미" 시트의
    행이며, 그 시트의 현재 체력·스킬·패시브 그대로 들어온다. 코스트는 가득
    찬 상태로 들어와 같은 라운드에 바로 행동할 수 있다.

    처리 시점은 이동과 같다 — 에너미 스킬이면 행동 선언(PRE) 때 바로 필드에
    나타난다.
    """

    def get_summon_list(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        raw_targets: tuple[CharacterId | BattlefieldColumnIndex, ...],
    ) -> list[SummonData]:
        names = [t for t in raw_targets if isinstance(t, CharacterId)]
        columns = [t for t in raw_targets if isinstance(t, BattlefieldColumnIndex)]
        # 입력 형식은 SkillTargetRuleSummon이 이미 검증했다.
        if len(names) != 1 or len(columns) != 1:
            return []
        return [
            SummonData(
                character_id=context.resolve_summon_id(names[0]),
                column=columns[0],
                faction=context.characters[holder].faction,
            )
        ]

    def _expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
        raw_targets: tuple = (),
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
        list[BuffRemoveData],
    ]:
        return ([], [], [], [], [])
