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


class SkillEffectDamage(SkillEffectBase):
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
        assert self.value is not None and self.value_source is not None

        if self.value_source is ValueSourceType.FIXED:
            damage_value = BaseValueIndicator(ValueSourceType.FIXED, self.value)
        else:
            damage_value = BaseValueIndicator(
                value_source=self.value_source,
                coefficient=FloatValueModifier(
                    source_name="계수", value=self.value / 100
                ),
            )
        is_magic_attack = context.characters[holder].status.is_magic_attacker
        return (
            [],
            [
                DamageData(
                    attacker_id=holder,
                    target_id=target,
                    value=damage_value,
                    is_magic_attack=is_magic_attack,
                )
                for target in targets
            ],
            [],
            [],
        )


class SkillEffectDamageReverse(SkillEffectDamage):
    """시전자의 공격 속성과 반대 속성으로 대미지를 입히는 스킬 효과."""

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
        _, damage_list, _, _ = super().expand(context, holder, targets)
        reversed_damage_list = [
            DamageData(
                attacker_id=d.attacker_id,
                target_id=d.target_id,
                value=d.value,
                is_magic_attack=not d.is_magic_attack,
            )
            for d in damage_list
        ]
        return [], reversed_damage_list, [], []
