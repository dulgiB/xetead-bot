from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectAddBuff(SkillEffectBase):
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
                    # 조건부 부여 게이트: 처리 시점(_process_buff_add)에서 판정한다.
                    # parse_skill_effect()가 "ConsumedBuffStackCountCondition"(스킬 조건)을
                    # 이미 gate_value_source/gate_value로 변환해두므로 그대로 전달만 한다.
                    gate_value_source=self.gate_value_source,
                    gate_value=self.gate_value,
                )
                for target in targets
            ],
            [],
        )
