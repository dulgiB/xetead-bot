from typing import TYPE_CHECKING, Optional

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from utils.battle_helpers import COLUMN_COUNT

from battle.objects.define import BattlefieldColumnIndex, ValueSourceType
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import (
    SkillEffectBase,
    departure_column,
    landing_column,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def _max_anchor(span: int) -> int:
    """여러 열을 차지하는 캐릭터가 설 수 있는 가장 오른쪽 기준 열. 기준 열은
    항상 가장 왼쪽이므로, 오른쪽 끝이 전장을 넘지 않으려면 여기까지다."""
    return COLUMN_COUNT - span


def _move_toward(
    from_pos: BattlefieldColumnIndex,
    toward_pos: BattlefieldColumnIndex,
    steps: int,
    span: int = 1,
) -> BattlefieldColumnIndex:
    if from_pos.value < toward_pos.value:
        return BattlefieldColumnIndex(min(_max_anchor(span), from_pos.value + steps))
    elif from_pos.value > toward_pos.value:
        return BattlefieldColumnIndex(max(0, from_pos.value - steps))
    return from_pos  # 동일 위치면 이동 없음


def _move_away_from(
    from_pos: BattlefieldColumnIndex,
    away_from: BattlefieldColumnIndex,
    steps: int,
    span: int = 1,
) -> BattlefieldColumnIndex:
    if from_pos.value < away_from.value:
        return BattlefieldColumnIndex(max(0, from_pos.value - steps))
    elif from_pos.value > away_from.value:
        return BattlefieldColumnIndex(min(_max_anchor(span), from_pos.value + steps))
    return from_pos  # 동일 위치면 방향 불명, 이동 없음


def _span_of(context: "BattlefieldContext", char_id: CharacterId) -> int:
    character = context.characters.get(char_id)
    return character.span if character is not None else 1


class SkillEffectMove(SkillEffectBase):
    """대상(또는 시전자)을 옮긴다. 시전자 위치를 기준으로 삼는 값 소스(시전자의
    위치로·시전자 쪽으로·시전자 반대쪽으로)는 departure_column()으로 읽는다 —
    `[이동/2열 - 끌어오기/대상]`처럼 앞 파트가 시전자를 옮겼으면 그 목적지가
    기준이어야 하는데, 전개 시점의 전장 위치는 아직 이동 전이다."""

    @property
    def lands_on_target_column(self) -> bool:
        return self.value_source == ValueSourceType.TARGET_CURR_POSITION

    def holder_destination(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
        raw_targets: tuple = (),
    ) -> Optional[BattlefieldColumnIndex]:
        # _expand()는 부수효과가 없으므로 그대로 전개해 시전자의 이동만 읽는다.
        # 자신을 대상으로 한 강제 이동(시전자 지정 가능한 밀어내기 등)도 잡힌다.
        destination = None
        for move in self.expand(context, holder, targets, raw_targets)[0]:
            if move.character_id == holder:
                destination = move.to_position
        return destination

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
        assert self.value_source is not None

        if self.value_source == ValueSourceType.FIXED:
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=BattlefieldColumnIndex(self.value),
                        is_forced=target != holder,
                    )
                    for target in targets
                ],
                [],
                [],
                [],
                [],
            )

        elif self.value_source == ValueSourceType.SELF_CURR_POSITION:
            holder_pos = departure_column(context, holder)
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=holder_pos,
                        is_forced=target != holder,
                    )
                    for target in targets
                ],
                [],
                [],
                [],
                [],
            )

        elif self.value_source == ValueSourceType.TARGET_CURR_POSITION:
            return (
                [
                    MoveData(
                        character_id=holder,
                        to_position=landing_column(context, target, raw_targets),
                        is_forced=False,
                    )
                    for target in targets
                ],
                [],
                [],
                [],
                [],
            )

        elif self.value_source == ValueSourceType.TOWARD_HOLDER:
            steps = self.value if self.value is not None else 1
            holder_pos = departure_column(context, holder)
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=_move_toward(
                            context.find_character_position(target),
                            holder_pos,
                            steps,
                            _span_of(context, target),
                        ),
                        is_forced=target != holder,
                    )
                    for target in targets
                ],
                [],
                [],
                [],
                [],
            )

        elif self.value_source == ValueSourceType.INPUT_COLUMN:
            columns = [t for t in raw_targets if isinstance(t, BattlefieldColumnIndex)]
            if not columns:
                # 열을 지정하지 않으면 이동 없이 현재 위치를 유지한다.
                return ([], [], [], [], [])
            to_pos = columns[0]
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=to_pos,
                        is_forced=target != holder,
                    )
                    for target in targets
                ],
                [],
                [],
                [],
                [],
            )

        elif self.value_source == ValueSourceType.AWAY_FROM_HOLDER:
            steps = self.value if self.value is not None else 1
            holder_pos = departure_column(context, holder)
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=_move_away_from(
                            context.find_character_position(target),
                            holder_pos,
                            steps,
                            _span_of(context, target),
                        ),
                        is_forced=target != holder,
                    )
                    for target in targets
                ],
                [],
                [],
                [],
                [],
            )

        else:
            raise ValueError(self.value_source)
