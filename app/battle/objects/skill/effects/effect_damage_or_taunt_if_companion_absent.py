from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.companion import companion_id_for, is_companion_alive
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


class SkillEffectDamageOrTauntIfCompanionAbsent(SkillEffectBase):
    """holder의 동료가 살아 있으면 value% 대미지 + 대상에게 buff_id(도발 등)
    부여, 동료가 없으면 도발 없이 더 높은 고정 계수(_NO_COMPANION_COEFFICIENT)로
    대미지만 입힌다."""

    _NO_COMPANION_COEFFICIENT: ClassVar[int] = 250

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
        assert (
            self.value is not None
            and self.value_source is not None
            and self.buff_id is not None
        )
        is_magic_attack = context.characters[holder].status.is_magic_attacker
        companion_alive = is_companion_alive(context, companion_id_for(holder))
        coefficient = self.value if companion_alive else self._NO_COMPANION_COEFFICIENT

        damage_list = [
            DamageData(
                attacker_id=holder,
                target_id=target,
                value=BaseValueIndicator(
                    value_source=self.value_source,
                    coefficient=FloatValueModifier(
                        source_name="계수", value=coefficient
                    ),
                ),
                is_magic_attack=is_magic_attack,
            )
            for target in targets
        ]
        buff_add_list = (
            [
                BuffAddData(given_by=holder, applied_to=target, buff_id=self.buff_id)
                for target in targets
            ]
            if companion_alive
            else []
        )
        return [], damage_list, [], buff_add_list, []
