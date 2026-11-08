from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_stats import CombatStats


class SkillEffectSuppressPassives(SkillEffectBase):
    """범위 안의 캐릭터가 지닌 패시브 스킬("스킬_패시브" 시트)을 걸려 있는
    동안 무효화한다.

    패시브 래퍼(PassiveSkillWrapperBuff)는 그대로 등록해 둔 채 발동만 막는다
    (PassiveSkillWrapperEvent.is_applied()) — 걷히면 다음 트리거부터 다시
    발동한다. 버프_패시브 모디파이어·스킬 효과 경로·반응형 트리거·도발 무시
    표시가 모두 같은 지점을 지나므로 경로를 가리지 않는다. 이미 패시브가
    부여해 둔 버프는 걷지 않는다 — 부여된 뒤에는 출처가 패시브인지 스킬인지
    구분되지 않는 일반 버프다.

    SkillEffectFieldStatOffset과 같은 상시 상태라 expand()로 전개되지 않는다.
    """

    requires_holder_character: ClassVar[bool] = False
    is_standing_state: ClassVar[bool] = True

    def apply_standing_state(self, stats: "CombatStats", *, revert: bool) -> None:
        if revert:
            stats.remove_passive_suppression()
        else:
            stats.add_passive_suppression()

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
