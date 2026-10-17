from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_stats import CombatStats


class _SkillKindBonusBase(SkillEffectBase):
    """스킬이 적층형 버프/디버프를 부여하는지에 따라 갈리는 보정의 공통 부모.

    걸려 있는 동안 유지되는 상태라 필드 효과·부적에서 쓴다. 보정 자체는
    스킬을 처리하는 쪽이 대상의 CombatStats를 읽어 반영한다 — 스택은 부여
    데이터를 만드는 전개 시점(command_expanders), 대미지는 계산기 생성
    시점(command_calculator)에 얹는다.

    "스킬"은 스킬 커맨드만 뜻한다. 기본 공격과 아이템은 해당하지 않는다.
    """

    requires_holder_character: ClassVar[bool] = False
    is_standing_state: ClassVar[bool] = True

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


class SkillEffectStackSkillBonus(_SkillKindBonusBase):
    """적층형 버프/디버프를 부여하는 스킬이 그 버프마다 `value_N`스택을 더
    부여한다."""

    def apply_standing_state(self, stats: "CombatStats", *, revert: bool) -> None:
        stats.set_stack_skill_bonus(self.value or 0, revert=revert)


class SkillEffectPlainSkillDamageBonus(_SkillKindBonusBase):
    """적층형 버프/디버프를 부여하지 않는 스킬의 대미지가 `value_N`% 증가한다.
    주는 대미지 버프와 같이 배율로 얹히므로 "고정" 대미지에는 붙지 않는다."""

    def apply_standing_state(self, stats: "CombatStats", *, revert: bool) -> None:
        stats.set_plain_skill_damage_bonus(self.value or 0, revert=revert)
