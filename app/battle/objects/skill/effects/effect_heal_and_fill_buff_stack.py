import math
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import CombatStatType, ValueSourceType
from battle.objects.models import BaseValueIndicator, CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectHealAndFillBuffStack(SkillEffectBase):
    """buff_id 적층형 버프의 "더 쌓을 수 있는 여유 스택 수" × value%만큼 대상을
    회복시키고, 시전자 자신의 해당 버프 스택을 즉시 최대치까지 채운다. 회복
    시도량이 대상에게 필요한 회복량(최대 체력 - 현재 체력)을 초과하면, 그
    초과분만큼 시전자 자신이 회복한다.

    주사위나 스탯 굴림이 개입하지 않는 결정론적 계산이라 expand() 시점에
    전부 즉시 계산해 FIXED 값으로 반환한다.
    """

    def _expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
        list[BuffRemoveData],
    ]:
        assert self.buff_id is not None and self.value is not None

        max_stack = context.get_buff_data_by_id(self.buff_id).max_stack or 0
        current_stack = context.get_buff_stack(holder, self.buff_id)
        space = max(0, max_stack - current_stack)
        heal_amount = math.floor(space * self.value / 100)

        heal_list: list[HealData] = []
        total_overflow = 0
        for target in targets:
            target_char = context.characters[target]
            missing_hp = (
                target_char.status[CombatStatType.MAX_HP] - target_char.status.curr_hp
            )
            target_heal = min(heal_amount, max(0, missing_hp))
            total_overflow += max(0, heal_amount - target_heal)
            heal_list.append(
                HealData(
                    healer_id=holder,
                    target_id=target,
                    value=BaseValueIndicator(ValueSourceType.FIXED, target_heal),
                )
            )

        if total_overflow > 0:
            heal_list.append(
                HealData(
                    healer_id=holder,
                    target_id=holder,
                    value=BaseValueIndicator(ValueSourceType.FIXED, total_overflow),
                )
            )

        buff_add_list = (
            [
                BuffAddData(
                    given_by=holder,
                    applied_to=holder,
                    buff_id=self.buff_id,
                    stack_value=space,
                )
            ]
            if space > 0
            else []
        )

        return [], [], heal_list, buff_add_list, []
