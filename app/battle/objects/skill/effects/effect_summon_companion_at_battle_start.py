from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.companion import companion_id_for
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


class SkillEffectSummonCompanionAtBattleStart(SkillEffectBase):
    """전투 시작 시 발동하는 패시브 전용 효과. holder의 동료를
    (아직 없다면) 소환한다. value를 동료의 최대 체력 비율(%)로 쓴다.

    다른 SkillEffectBase 구현체와 달리 이 클래스는 `_expand()`에서 즉시
    `context.spawn_companion_if_absent()`를 호출해 상태를 바꾼다 — 보통
    스킬 효과는 실제 커맨드 검증(try_expansion_if_valid)이 통과하기 전에도
    미리 expand()가 호출될 수 있어 부수효과를 곧바로 일으키면 안 되지만,
    이 효과는 오직 PassiveSkillWrapperBuff의 ON_BATTLE_START 경로
    (BuffContainer._apply_round_events)로만 호출되며 그 경로는 검증 실패로
    되돌릴 일이 없는 즉시 커밋 경로다. 그래서 여기서는 안전하다.
    """

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
        assert self.value is not None
        context.spawn_companion_if_absent(holder, companion_id_for(holder), self.value)
        return [], [], [], [], []
