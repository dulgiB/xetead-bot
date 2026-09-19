from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectConditionalBuff(SkillEffectBase):
    """대상별 조건(`target_condition_N`)을 만족하는 대상에게 버프를 부여하고,
    만족하지 않는 대상에게서는 **이 효과가 걸어 둔 버프를 회수한다.**

    "체력이 N% 이하인 동안"처럼 상태를 따라다녀야 하는 효과용이다. 부여만
    하는 효과(SkillEffectAddBuff + target_condition)로는 조건에서 벗어났을 때
    풀리지 않아, 지속시간이 끝날 때까지 남는다.

    회수는 이 효과의 시전자가 건 인스턴스만 골라 지운다 — 같은 버프를 다른
    데서 받았다면 그건 남아야 한다. 부여와 회수를 한 번의 평가에서 함께
    처리해야 하므로 expand()의 자동 대상 필터를 끄고 전체 목록을 받는다.

    회수는 SkillEffectRemoveDebuffs와 같이 expand() 시점에 즉시 수행한다 —
    반환하는 buff_remove_list는 적층 버프의 스택 차감용이라 부여자를 가릴 수
    없고, 매 라운드 도는 이 평가에서 "소모" 로그를 남길 일도 아니다.
    """

    requires_holder_character: ClassVar[bool] = False
    applies_target_condition_itself: ClassVar[bool] = True

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

        buff_add_list: list[BuffAddData] = []
        for target in targets:
            if self.passes_target_condition(context, target):
                buff_add_list.append(
                    BuffAddData(
                        given_by=holder,
                        applied_to=target,
                        buff_id=self.buff_id,
                        add_timing=self.buff_add_timing,
                        stack_value=self.buff_stack_cap or 1,
                    )
                )
                continue

            existing = context.buff_container.get_buff(
                target, self.buff_id, given_by=holder
            )
            if existing is not None:
                context.buff_container.remove(existing.uid)

        return ([], [], [], buff_add_list, [])
