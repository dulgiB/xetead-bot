from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectAddBuffPerDamagedColumn(SkillEffectBase):
    """holder를 중심으로 좌우 value열(자신의 열 포함) 범위에서, 이번 라운드에
    아군이 한 명이라도 피격된 **열의 개수**만큼 buff_id 스택을 부여한다.

    "피격당한 아군 수"가 아니라 "피격당한 열 수"라는 점이 핵심이다 — 한 열에서
    세 명이 맞아도 그 열 몫은 1스택이다. 기존 Condition은 "범위 안에 피격자가
    있는가"라는 boolean만 답할 수 있어(AllyInSameColumnWasAttackedCondition 등)
    열 단위 개수를 셀 수 없으므로 전용 effect로 둔다.

    damaged_this_round를 읽으므로 라운드의 피격이 모두 확정된 뒤에 평가돼야
    한다(requires_round_resolved).
    """

    requires_round_resolved: ClassVar[bool] = True

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
        # value는 수치가 아니라 좌우로 몇 열까지 볼지(반경)다. 0이면 자신의 열만.
        radius = self.value if self.value is not None else 0

        holder_char = context.characters.get(holder)
        if holder_char is None:
            return [], [], [], [], []
        holder_column = context.find_character_position(holder).value

        # 동료(소환수)를 제외하지 않는 것은 의도된 동작이다 — 같은 범위 판정을
        # 하는 기존 조건들(_characters_in_holder_scope 계열)도 동료를 세므로
        # "누군가 맞았다"의 기준을 둘 사이에서 일치시킨다.
        damaged_columns = {
            context.find_character_position(char_id).value
            for char_id in context.damaged_this_round
            if char_id in context.characters
            and context.characters[char_id].faction == holder_char.faction
        }
        column_count = sum(
            1
            for column in range(holder_column - radius, holder_column + radius + 1)
            if column in damaged_columns
        )
        if column_count <= 0:
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
                    stack_value=column_count,
                )
                for target in targets
            ],
            [],
        )
