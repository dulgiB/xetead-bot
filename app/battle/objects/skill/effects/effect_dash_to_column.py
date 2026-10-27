from typing import TYPE_CHECKING, Optional

from battle.exceptions import CommandValidationError, error_column_target_required
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
from battle.objects.skill.models import SkillEffectBase, departure_column
from utils.battle_helpers import columns_for_span

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def dash_path_columns(
    departure: BattlefieldColumnIndex, destination: BattlefieldColumnIndex, span: int
) -> list[BattlefieldColumnIndex]:
    """출발 위치에서 도착 위치로 옮겨 가며 시전자가 새로 밟는 열. 출발할 때
    이미 차지하던 열은 빼고, 도착해 차지하는 열은 넣는다. 한 열짜리면
    SkillEffectSplashAlongPath와 같은 "출발 열 제외, 도착 열 포함"이다."""
    if departure == destination:
        return []
    start_columns = set(columns_for_span(departure, span))
    first = min(departure.value, destination.value)
    last = max(departure.value, destination.value) + max(1, span) - 1
    return [
        BattlefieldColumnIndex(value)
        for value in range(first, last + 1)
        if BattlefieldColumnIndex(value) not in start_columns
        and value < BattlefieldColumnIndex.NONE.value
    ]


class SkillEffectDashToColumn(SkillEffectBase):
    """지정한 열로 돌진하며 지나간 열의 모든 적에게 같은 계수의 대미지를 입힌다.

    SkillEffectSplashAlongPath와 달리 주대상이 없다 — 캐릭터가 없는 열도
    지정할 수 있고, 경로 위의 적은 모두 같은 대미지를 받는다. 열 입력이
    필요하므로 SkillTargetRuleColumn(target_count 1)과 쓴다. 그 규칙이
    잡아 주는 대상(도착 열의 적)은 쓰지 않고 경로를 직접 계산한다.

    시전자의 이동과 경로 대미지를 한 효과가 함께 낸다. 출발 열은
    departure_column()으로 읽으므로, 에너미가 행동 선언 때 이동하고 적 공격
    정산 때 대미지를 재전개해도 선언 직전 위치에서 경로를 잰다. 열 광역
    규칙이라 도발은 적용되지 않는다(command_expanders가 ignores_taunt를 켠다).

    다열 에너미는 경로와 겹친 열 수만큼 맞는다(열 광역기와 같은 규칙).
    """

    def dash_destination(
        self, raw_targets: "tuple[CharacterId | BattlefieldColumnIndex, ...]"
    ) -> Optional[BattlefieldColumnIndex]:
        return next(
            (t for t in raw_targets if isinstance(t, BattlefieldColumnIndex)), None
        )

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
        destination = self.dash_destination(raw_targets)
        if destination is None:
            raise CommandValidationError(error_column_target_required())

        character = context.characters[holder]
        departure = departure_column(context, holder)
        path_columns = dash_path_columns(departure, destination, character.span)

        foe_map = context.position_map[character.foe_faction]
        path_targets = [
            char_id for column in path_columns for char_id in foe_map[column].values()
        ]

        if self.value_source is ValueSourceType.FIXED:
            damage_value = BaseValueIndicator(ValueSourceType.FIXED, self.value)
        else:
            damage_value = BaseValueIndicator(
                value_source=self.value_source,
                coefficient=FloatValueModifier(source_name="계수", value=self.value),
            )
        return (
            [MoveData(character_id=holder, to_position=destination, is_forced=True)],
            [
                DamageData(
                    attacker_id=holder,
                    target_id=char_id,
                    value=damage_value,
                    is_magic_attack=character.status.is_magic_attacker,
                )
                for char_id in path_targets
            ],
            [],
            [],
            [],
        )
