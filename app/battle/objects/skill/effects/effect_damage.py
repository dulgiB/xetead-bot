from dataclasses import replace
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


class SkillEffectDamage(SkillEffectBase):
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
            damage_value = BaseValueIndicator(ValueSourceType.FIXED, self.value)
        else:
            damage_value = BaseValueIndicator(
                value_source=self.value_source,
                coefficient=FloatValueModifier(source_name="계수", value=self.value),
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
                    ignores_taunt=self.ignores_taunt,
                    triggers_holder_action_buffs=not self.ignores_defensive_buffs,
                )
                for target in targets
            ],
            [],
            [],
            [],
        )


class SkillEffectDamageReverse(SkillEffectDamage):
    """시전자의 공격 속성과 반대 속성으로 대미지를 입히는 스킬 효과."""

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
        _, damage_list, _, _, _ = super()._expand(context, holder, targets, raw_targets)
        reversed_damage_list = [
            DamageData(
                attacker_id=d.attacker_id,
                target_id=d.target_id,
                value=d.value,
                is_magic_attack=not d.is_magic_attack,
            )
            for d in damage_list
        ]
        return [], reversed_damage_list, [], [], []


class SkillEffectDamageByTargetHpRatio(SkillEffectDamage):
    """대미지에 대상의 남은 체력 비율을 곱한다(체력 50%면 × 0.5). 비율은
    대미지가 적용되는 순간의 체력으로 정하므로, 같은 커맨드에서 여러 번
    맞으면 뒤의 타격일수록 약해진다. 이 효과만으로는 대상을 쓰러뜨릴 수 없다."""

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
        moves, damage_list, heals, buff_adds, buff_removes = super()._expand(
            context, holder, targets, raw_targets
        )
        return (
            moves,
            [replace(d, scales_with_target_hp_ratio=True) for d in damage_list],
            heals,
            buff_adds,
            buff_removes,
        )
