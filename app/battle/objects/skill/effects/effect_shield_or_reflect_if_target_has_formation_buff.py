from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectShieldOrReflectIfTargetHasFormationBuff(SkillEffectBase):
    """대상 각각에 대해 [Formation] 버프 보유 여부를 확인해, 보유 중이면 대체
    버프를, 아니면 기본 버프(`buff_id_N`)를 부여한다.
    대체 버프는 시트의 `reference_buff_id_N`에서 온다.
    """

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
        alternate_buff_id = self.reference_buff_id
        buff_add_list = []
        for target in targets:
            buff_id = self.buff_id
            if alternate_buff_id is not None and any(
                buff.uid.buff_name == self._GATE_BUFF_CLASS_NAME
                for buff in context.buff_container.get_buffs_by(target, None)
            ):
                buff_id = alternate_buff_id
            buff_add_list.append(
                BuffAddData(
                    given_by=holder,
                    applied_to=target,
                    buff_id=buff_id,
                    add_timing=self.buff_add_timing,
                    stack_value=self.buff_stack_cap or 1,
                )
            )
        return [], [], [], buff_add_list, []
