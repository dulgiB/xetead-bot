from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import BattlefieldColumnIndex, ValueSourceType
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectMove(SkillEffectBase):
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

        if self.value_source == ValueSourceType.FIXED:
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=BattlefieldColumnIndex(self.value),
                    )
                    for target in targets
                ],
                [],
                [],
                [],
            )
        elif self.value_source == ValueSourceType.SELF_CURR_POSITION:
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=context.find_character_position(holder),
                    )
                    for target in targets
                ],
                [],
                [],
                [],
            )
        elif self.value_source == ValueSourceType.TARGET_CURR_POSITION:
            return (
                [
                    MoveData(
                        character_id=target,
                        to_position=context.find_character_position(target),
                    )
                    for target in targets
                ],
                [],
                [],
                [],
            )
        else:
            raise ValueError(self.value_source)
