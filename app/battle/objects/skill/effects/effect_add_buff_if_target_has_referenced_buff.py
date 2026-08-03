from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectAddBuffIfTargetHasReferencedBuff(SkillEffectBase):
    """대상이 reference_buff_id 버프를 이미 보유하고 있을 때만 buff_id
    버프를 부여한다(선행 디버프 존재를 요구하는 후속 콤보 효과용)."""

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
        assert self.buff_id is not None and self.reference_buff_id is not None
        buff_add_list = [
            BuffAddData(
                given_by=holder,
                applied_to=target,
                buff_id=self.buff_id,
                add_timing=self.buff_add_timing,
            )
            for target in targets
            if context.get_buff_stack(target, self.reference_buff_id) > 0
        ]
        return [], [], [], buff_add_list, []
