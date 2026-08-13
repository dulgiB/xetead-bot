from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectAddBuffAtTargetColumn(SkillEffectBase):
    """대상의 현재 위치(열)를 buff_id 버프의 수치로 스냅샷해 부여한다(부여
    이후 대상이 이동해도 이미 부여된 버프의 수치는 갱신되지 않는다)."""

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
        assert self.buff_id is not None
        return (
            [],
            [],
            [],
            [
                BuffAddData(
                    given_by=holder,
                    applied_to=target,
                    buff_id=self.buff_id,
                    add_timing=self.buff_add_timing,
                    value_override=context.find_character_position(target).value,
                )
                for target in targets
            ],
            [],
        )
