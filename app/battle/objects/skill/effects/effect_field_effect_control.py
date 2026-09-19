from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.field_effect.models import FieldEffectOp
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class _FieldEffectControlBase(SkillEffectBase):
    """필드 효과를 올리거나 걷는 효과의 공통 부모.

    대상이 없다 — 전장 자체에 거는 일이라 대상 목록과 무관하게 한 번만
    일어난다. 그래서 expand()는 아무것도 만들지 않고, 실제 요청은
    get_field_effect_ops()로 나간다.
    """

    requires_holder_character: ClassVar[bool] = False
    _REMOVE: ClassVar[bool] = False

    def get_field_effect_ops(
        self, context: "BattlefieldContext", holder: CharacterId
    ) -> list[FieldEffectOp]:
        if not self.field_effect_id:
            return []
        return [FieldEffectOp(effect_id=self.field_effect_id, remove=self._REMOVE)]

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
        return ([], [], [], [], [])


class SkillEffectAddFieldEffect(_FieldEffectControlBase):
    """`field_effect_id_N`이 가리키는 필드 효과를 전장에 올린다."""

    _REMOVE: ClassVar[bool] = False


class SkillEffectRemoveFieldEffect(_FieldEffectControlBase):
    """`field_effect_id_N`이 가리키는 필드 효과를 전장에서 걷는다.
    그 효과가 부여해 둔 버프와 스탯 증감도 함께 회수된다."""

    _REMOVE: ClassVar[bool] = True
