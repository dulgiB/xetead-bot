from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectAddBuff(SkillEffectBase):
    # 홀더를 given_by로 실어 나르기만 하고 스탯·위치를 읽지 않는다.
    requires_holder_character: ClassVar[bool] = False

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
                    stack_value=self.buff_stack_cap or 1,
                    # 조건부 부여 게이트는 처리 시점에 판정되므로 전달만 한다.
                    gate_value_source=self.gate_value_source,
                    gate_value=self.gate_value,
                )
                for target in targets
            ],
            [],
        )
