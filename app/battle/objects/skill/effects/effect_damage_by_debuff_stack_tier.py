from typing import TYPE_CHECKING, ClassVar

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


class SkillEffectDamageByDebuffStackTier(SkillEffectBase):
    """대상에게 걸린 buff_id 적층형 디버프의 현재 스택 수에 따라 대미지 계수와
    스택 처리 방식이 갈리는 스킬 효과(최대 적층 5 기준 3단계).

    - 0~2스택: 낮은 계수로 대미지 + 스택 1 추가(재적용이라 BuffContainer.add()가
      지속시간도 함께 갱신한다)
    - 3~4스택: 중간 계수로 대미지 + 스택 1 추가(동일)
    - 5스택(최대): 최고 계수로 대미지 + 스택 전량 제거
    """

    _MID_TIER_THRESHOLD: ClassVar[int] = 3
    _MAX_TIER_THRESHOLD: ClassVar[int] = 5
    _LOW_TIER_COEFFICIENT: ClassVar[int] = 280
    _MID_TIER_COEFFICIENT: ClassVar[int] = 350
    _MAX_TIER_COEFFICIENT: ClassVar[int] = 500

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
        assert self.value_source is not None and self.buff_id is not None
        is_magic_attack = context.characters[holder].status.is_magic_attacker

        damage_list: list[DamageData] = []
        buff_add_list: list[BuffAddData] = []
        buff_remove_list: list[BuffRemoveData] = []

        for target in targets:
            stack_count = context.get_buff_stack(target, self.buff_id)
            if stack_count >= self._MAX_TIER_THRESHOLD:
                coefficient = self._MAX_TIER_COEFFICIENT
                buff_remove_list.append(
                    BuffRemoveData(
                        applied_to=target,
                        buff_id=self.buff_id,
                        requested_amount=stack_count,
                    )
                )
            else:
                coefficient = (
                    self._MID_TIER_COEFFICIENT
                    if stack_count >= self._MID_TIER_THRESHOLD
                    else self._LOW_TIER_COEFFICIENT
                )
                buff_add_list.append(
                    BuffAddData(
                        given_by=holder, applied_to=target, buff_id=self.buff_id
                    )
                )

            damage_list.append(
                DamageData(
                    attacker_id=holder,
                    target_id=target,
                    value=BaseValueIndicator(
                        value_source=self.value_source,
                        coefficient=FloatValueModifier(
                            source_name="계수", value=coefficient
                        ),
                    ),
                    is_magic_attack=is_magic_attack,
                )
            )

        return [], damage_list, [], buff_add_list, buff_remove_list
