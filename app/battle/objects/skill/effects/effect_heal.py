from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
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
        assert self.value is not None and self.value_source is not None

        if self.value_source is ValueSourceType.FIXED:
            heal_value = BaseValueIndicator(ValueSourceType.FIXED, self.value)
        else:
            heal_value = BaseValueIndicator(
                value_source=self.value_source,
                coefficient=FloatValueModifier(source_name="계수", value=self.value),
            )
        return (
            [],
            [],
            [
                HealData(healer_id=holder, target_id=target, value=heal_value)
                for target in targets
            ],
            [],
            [],
        )
