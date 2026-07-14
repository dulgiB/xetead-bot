from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
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


class SkillEffectConsumeStackForDamage(SkillEffectBase):
    """buff_id 적층형 버프의 스택을 대상별로 최대 buff_stack_cap만큼 소모(제거)
    하면서, 동시에 그 소모량 × value%만큼 대미지를 추가로 입힌다.

    제거와 대미지를 같은 effect(같은 effect_seq_number)로 함께 반환하는 이유:
    CommandPartCalculator.process()는 같은 인덱스에 대해 항상 _process_buff_remove()를
    _process_damage()보다 먼저 실행하므로, 이 effect가 반환한 BuffRemoveData가 먼저
    처리되어 result_value(실제 소모량)가 기록된 뒤 같은 슬롯의 DamageData가
    CONSUMED_BUFF_STACK 값소스로 그 값을 즉시 조회할 수 있다.

    스택은 targets(대미지 대상)의 것을 소모한다. 시전자 자신의 스택을 소모하며
    다른 대상에게 대미지를 주는 패턴은 지원하지 않는다 — target_override는
    제거 대상과 대미지 대상을 함께 옮기므로 분리가 불가능하다. 필요해지면
    별도 필드가 추가로 필요하다.
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
        assert self.buff_id is not None
        assert self.value is not None and self.value_source is not None
        cap = self.buff_stack_cap or 0

        buff_remove_list = [
            BuffRemoveData(applied_to=target, buff_id=self.buff_id, requested_amount=cap)
            for target in targets
        ]

        is_magic_attack = context.characters[holder].status.is_magic_attacker
        damage_value = BaseValueIndicator(
            value_source=self.value_source,
            coefficient=FloatValueModifier(source_name="계수", value=self.value),
        )
        damage_list = [
            DamageData(
                attacker_id=holder,
                target_id=target,
                value=damage_value,
                is_magic_attack=is_magic_attack,
            )
            for target in targets
        ]

        return [], damage_list, [], [], buff_remove_list
