from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectAddBuff(SkillEffectBase):
    def expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
    ]:
        assert self.buff_id is not None
        return (
            [],
            [],
            [],
            [
                BuffAddData(
                    given_by=holder,
                    applied_to=target,
                    buff_id=self.buff_id,
                    add_timing=self.buff_add_timing,
                )
                for target in targets
            ],
        )
