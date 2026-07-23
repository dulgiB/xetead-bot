from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.companion import is_companion_alive
from battle.objects.define import ValueSourceType
from battle.objects.models import BaseValueIndicator, CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectSpendCompanionHpOrSummon(SkillEffectBase):
    """holder의 동료가 살아 있으면 동료의 체력을 value만큼 소모(고정 대미지로
    표현 — 부족해도 0으로 clamp된다)하고 holder 자신에게 buff_id를 부여한다.
    동료가 없으면 대미지/버프 없이 _RESUMMON_HP_PERCENT% 체력으로 재소환한다.

    재소환 분기는 `context.revive_companion()`을 `_expand()`에서 직접
    호출해 즉시 반영한다 — 패시브가 전투 시작 시 항상 먼저 동료를 소환해
    이름(가디언 버프 id 기반)을 확정해 두므로, 이 효과는 그 이름을 다시
    알 필요 없이 재소환만 위임한다. 이 효과는 일반 스킬 커맨드 파이프라인
    (try_expansion_if_valid)을 통해 호출되므로, 같은 커맨드의 다른 파트가
    이 효과 이후에 검증 실패하면 이미 일어난 재소환은 롤백되지 않는다. 이
    조합(코스트 3 스킬 + 검증에 실패하는 다른 파트를 같은 커맨드에 함께
    쓰는 경우)은 실제로는 매우 드물고, 설령 발생해도 여분의 동료가 남는
    정도라 GM이 수동으로 정리할 수 있는 수준이므로 감수한다.
    """

    _RESUMMON_HP_PERCENT: ClassVar[int] = 10

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
        assert self.value is not None and self.buff_id is not None
        companion_id = context.find_companion_id(holder)

        if is_companion_alive(context, companion_id):
            damage_list = [
                DamageData(
                    attacker_id=holder,
                    target_id=companion_id,
                    value=BaseValueIndicator(ValueSourceType.FIXED, self.value),
                )
            ]
            buff_add_list = [
                BuffAddData(given_by=holder, applied_to=holder, buff_id=self.buff_id)
            ]
            return [], damage_list, [], buff_add_list, []

        context.revive_companion(holder, self._RESUMMON_HP_PERCENT)
        return [], [], [], [], []
