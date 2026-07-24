from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectAddBuffIfHolderHasFormationBuff(SkillEffectBase):
    """시전자가 [Formation] 버프를 보유한 상태일 때만 대상에게 버프를 부여한다."""

    _GATE_BUFF_CLASS_NAME: ClassVar[str] = "BuffFormation"

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
        has_gate_buff = any(
            buff.uid.buff_name == self._GATE_BUFF_CLASS_NAME
            for buff in context.buff_container.get_buffs_by(holder, None)
        )
        if not has_gate_buff:
            return [], [], [], [], []

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
                )
                for target in targets
            ],
            [],
        )
