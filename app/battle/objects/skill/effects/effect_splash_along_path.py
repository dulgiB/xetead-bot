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
from battle.objects.skill.models import (
    SkillEffectBase,
    departure_column,
    landing_column,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectSplashAlongPath(SkillEffectBase):
    """시전자의 원래 위치 ~ 주대상의 위치 사이 열에 있는 모든 적에게 대미지를
    입힌다. 출발 열은 빼고 도착 열은 넣는다 — 시전자가 지나가는 열만 친다.
    주대상은 착지 열에서만 빠지며, 같은 열의 대상을 치면 지나가는 열이 없다.

    돌진(SkillEffectMove의 TARGET_CURR_POSITION)과 함께 쓰이는 스킬을 위한
    효과로, 출발 열은 departure_column()으로 읽는다 — 같은 커맨드의 앞 파트
    이동을 반영하고, 에너미가 PRE에 이미 이동한 뒤 POST에 재전개될 때도
    선언 직전 위치를 쓴다.

    도착 열은 주대상의 착지 열(landing_column())이다. 다열 에너미는 걸친 열
    전부에 등록돼 있으므로, 경로와 겹친 열 수만큼 경로 대미지를 중복해서
    받는다(열 광역기와 같은 규칙). 다열 주대상도 착지 열 외에 경로와 겹친
    자기 열마다 경로 대미지를 받는다.
    """

    @property
    def lands_on_target_column(self) -> bool:
        return True

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

        from_pos = departure_column(context, holder)
        to_pos = landing_column(context, main_target, raw_targets)
        step = 1 if to_pos.value >= from_pos.value else -1
        path_columns = range(from_pos.value + step, to_pos.value + step, step)

        foe_faction = context.characters[holder].foe_faction
        splash_targets = [
            char_id
            for value in path_columns
            for char_id in context.position_map[foe_faction][
                BattlefieldColumnIndex(value)
            ].values()
            # 주대상은 착지 열에서 주대상 대미지를 받으므로 그 열만 뺀다.
            if char_id != main_target or value != to_pos.value
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
