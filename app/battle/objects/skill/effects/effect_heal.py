from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import ValueSourceType
from battle.objects.models import (
    BaseValueIndicator,
    CharacterId,
    DamageData,
    FloatValueModifier,
    HealData,
    MoveData,
)
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectHeal(SkillEffectBase):
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
        assert self.value_source is not None

        if self.value_source is ValueSourceType.FIXED:
            heal_value = self.value
        else:
            heal_value = BaseValueIndicator(
                value_source=self.value_source,
                coefficient=FloatValueModifier(value=self.value / 100),
            )
        return (
            [],
            [],
            [
                HealData(healer_id=holder, target_id=target, value=heal_value)
                for target in targets
            ],
            [],
        )
