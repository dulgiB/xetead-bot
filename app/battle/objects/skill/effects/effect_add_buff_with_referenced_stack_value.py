from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectAddBuffWithReferencedStackValue(SkillEffectBase):
    """holder의 reference_buff_id 버프 스택 수 × value%를 새 버프의 수치로
    스냅샷해 targets에게 buff_id 버프를 부여한다(부여 이후 reference_buff_id
    스택이 바뀌어도 이미 부여된 버프의 수치는 갱신되지 않는다).

    holder가 reference_buff_id를 보유하지 않으면(스택 0) 아무 것도 하지
    않는다. required_target_buff_id가 채워져 있으면 그 버프를 보유한
    대상에게만, 그리고 이미 buff_id를 보유한 대상은 건너뛴 채(재부여 없이
    1회만 태그하는 콤보 용도) 부여한다 — 비어 있으면 대상 상태와 무관하게
    항상 재부여(수치/지속시간 갱신)한다."""

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
        assert (
            self.buff_id is not None
            and self.reference_buff_id is not None
            and self.value is not None
        )
        holder_stack = context.get_buff_stack(holder, self.reference_buff_id)
        if holder_stack <= 0:
            return [], [], [], [], []
        snapshot_value = holder_stack * self.value

        buff_add_list: list[BuffAddData] = []
        for target in targets:
            if self.required_target_buff_id is not None:
                if context.get_buff_stack(target, self.required_target_buff_id) <= 0:
                    continue
                if context.get_buff_stack(target, self.buff_id) > 0:
                    continue
            buff_add_list.append(
                BuffAddData(
                    given_by=holder,
                    applied_to=target,
                    buff_id=self.buff_id,
                    add_timing=self.buff_add_timing,
                    value_override=snapshot_value,
                )
            )
        return [], [], [], buff_add_list, []
