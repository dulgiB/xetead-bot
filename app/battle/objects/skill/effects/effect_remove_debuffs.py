from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import BuffType
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def _clearable_debuffs(context: "BattlefieldContext", target: CharacterId) -> list:
    return [
        b
        for b in context.buff_container.get_buffs_by(target, None)
        if b.buff_type == BuffType.DEBUFF and not b.duration.is_passive
    ]


class SkillEffectRemoveDebuffs(SkillEffectBase):
    """대상에게 걸린 패시브가 아닌 디버프를 전부 제거한다."""

    # 홀더를 given_by로 실어 나르기만 하고 스탯·위치를 읽지 않는다.
    requires_holder_character: ClassVar[bool] = False

    def get_debuff_clear_targets(
        self, context: "BattlefieldContext", targets: list[CharacterId]
    ) -> list[CharacterId]:
        return [target for target in targets if _clearable_debuffs(context, target)]

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
        for target in targets:
            for buff in _clearable_debuffs(context, target):
                context.buff_container.remove(buff.uid)
        return [], [], [], [], []
