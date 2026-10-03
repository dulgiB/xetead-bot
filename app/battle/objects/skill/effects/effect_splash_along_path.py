from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import BattlefieldColumnIndex, ValueSourceType
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


class SkillEffectSplashAlongPath(SkillEffectBase):
    """시전자의 원래 위치 ~ 주대상의 위치 사이 열에 있는 모든 적에게 대미지를
    입힌다. 출발 열은 빼고 도착 열은 넣는다 — 시전자가 지나가는 열만 친다.
    주대상 본인은 제외하며, 같은 열의 대상을 치면 지나가는 열이 없다.

    돌진(SkillEffectMove의 TARGET_CURR_POSITION)과 함께 쓰이는 스킬을 위한
    효과로, expand() 시점엔 아직 실제 이동이 적용되지 않으므로
    context.find_character_position(holder)가 시전자의 "원래" 위치를 그대로
    반환한다는 점을 이용한다.
    """

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
        assert len(targets) == 1
        main_target = targets[0]

        from_pos = context.find_character_position(holder)
        to_pos = context.find_character_position(main_target)
        step = 1 if to_pos.value >= from_pos.value else -1
        path_columns = range(from_pos.value + step, to_pos.value + step, step)

        foe_faction = context.characters[holder].foe_faction
        splash_targets = [
            char_id
            for value in path_columns
            for char_id in context.position_map[foe_faction][
                BattlefieldColumnIndex(value)
            ].values()
            if char_id != main_target
        ]

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
                    target_id=char_id,
                    value=damage_value,
                    is_magic_attack=is_magic_attack,
                )
                for char_id in splash_targets
            ],
            [],
            [],
            [],
        )
