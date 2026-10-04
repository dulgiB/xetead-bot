from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_stats import CombatStats


class SkillEffectRevivalCountFloor(SkillEffectBase):
    """범위 안의 캐릭터를 부활 `value_N`회 상태처럼 취급한다(실제 부활 횟수가
    그보다 많으면 실제 값을 쓴다).

    받는 대미지 증가와 턴당 코스트 증가에만 반영된다. 이동 코스트 증가와
    키워드 보정 사용 자격은 실제 부활 횟수를 본다 — 부활 경험 자체를 주는
    것이 아니라 부활 페널티·보너스의 수치만 끌어올리는 효과이기 때문이다.
    턴당 코스트는 라운드 시작 회복 때 반영되므로 도중에 범위에 들거나
    벗어나면 다음 라운드부터 바뀐다.

    SkillEffectFieldStatOffset과 같은 상시 상태라 expand()로 전개되지 않는다.
    """

    requires_holder_character: ClassVar[bool] = False
    is_standing_state: ClassVar[bool] = True

    @property
    def floor(self) -> int:
        return self.value or 0

    def apply_standing_state(self, stats: "CombatStats", *, revert: bool) -> None:
        if revert:
            stats.remove_revival_count_floor(self.floor)
        else:
            stats.add_revival_count_floor(self.floor)

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
