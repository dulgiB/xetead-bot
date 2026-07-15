from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import BattlefieldColumnIndex, ValueSourceType
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def _move_toward(
    from_pos: BattlefieldColumnIndex,
    toward_pos: BattlefieldColumnIndex,
    steps: int,
) -> BattlefieldColumnIndex:
    if from_pos.value < toward_pos.value:
        return BattlefieldColumnIndex(min(6, from_pos.value + steps))
    elif from_pos.value > toward_pos.value:
        return BattlefieldColumnIndex(max(0, from_pos.value - steps))
    return from_pos  # 동일 위치면 이동 없음


def _move_away_from(
    from_pos: BattlefieldColumnIndex,
    away_from: BattlefieldColumnIndex,
    steps: int,
) -> BattlefieldColumnIndex:
    if from_pos.value < away_from.value:
        return BattlefieldColumnIndex(max(0, from_pos.value - steps))
    elif from_pos.value > away_from.value:
        return BattlefieldColumnIndex(min(6, from_pos.value + steps))
    return from_pos  # 동일 위치면 방향 불명, 이동 없음


class SkillEffectMove(SkillEffectBase):
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
                        is_forced=True,
                    )
                    for target in targets
                ],
                [],
                [],
                [],
                [],
            )

        elif self.value_source == ValueSourceType.SELF_CURR_POSITION:
            holder_pos = context.find_character_position(holder)
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=holder_pos,
                        is_forced=True,
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
                        to_position=context.find_character_position(target),
                        is_forced=True,
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
            holder_pos = context.find_character_position(holder)
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=_move_toward(
                            context.find_character_position(target), holder_pos, steps
                        ),
                        is_forced=True,
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
                        is_forced=True,
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
            holder_pos = context.find_character_position(holder)
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=_move_away_from(
                            context.find_character_position(target), holder_pos, steps
                        ),
                        is_forced=True,
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
