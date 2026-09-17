from typing import TYPE_CHECKING, Optional

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import CombatStatType, ValueSourceType
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext

# value_source_N에 적는 스탯 종류 → 실제로 증감할 스탯.
# 최대 체력은 일부러 빠져 있다 — 전투 중에 최대 체력이 바뀌면 현재 체력
# 비율·표시·시트 반영이 함께 흔들려서 별개의 설계가 필요하다.
_OFFSETTABLE_STATS: dict[ValueSourceType, CombatStatType] = {
    ValueSourceType.STAT_ATK: CombatStatType.ATK,
    ValueSourceType.STAT_RANGE: CombatStatType.RANGE,
    ValueSourceType.STAT_COST_PER_TURN: CombatStatType.COST_PER_TURN,
}


class SkillEffectFieldStatOffset(SkillEffectBase):
    """필드 효과 전용: 범위 안의 캐릭터들에게 스탯 증감을 상시로 얹는다.

    `value_source_N`이 **어느 스탯을 바꾸는지**를, `value_N`이 증감량을
    정한다(음수면 감소). 다른 효과에서 `value_source_N`이 "수치를 어디서
    가져오는가"인 것과 달리 여기서는 대상 스탯을 가리킨다.

    다른 효과들과 달리 expand()로 전개되지 않는다 — 트리거에 반응해 한 번씩
    일어나는 일이 아니라, 필드 효과가 걸려 있는 동안 계속 유지되는 상태이기
    때문이다. FieldEffectContainer가 필드 효과를 올리고 걷을 때, 그리고 전투
    도중 참전한 캐릭터에게 이 선언을 직접 읽어 반영한다.
    """

    @property
    def stat_type(self) -> Optional[CombatStatType]:
        """증감할 스탯. 지원하지 않는 value_source면 None(설정 오류)."""
        if self.value_source is None:
            return None
        return _OFFSETTABLE_STATS.get(self.value_source)

    @property
    def offset(self) -> int:
        return self.value or 0

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
