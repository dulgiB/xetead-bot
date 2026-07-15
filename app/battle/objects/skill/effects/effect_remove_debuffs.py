from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectRemoveDebuffs(SkillEffectBase):
    """대상에게 걸린 패시브가 아닌 디버프를 전부 제거한다."""

    def _expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
        list[BuffRemoveData],
    ]:
        for target in targets:
            debuffs = [
                b
                for b in context.buff_container.get_buffs_by(target, None)
                if b.is_debuff and not b.duration.is_passive
            ]
            for buff in debuffs:
                context.buff_container.remove(buff.uid)
        return [], [], [], [], []
