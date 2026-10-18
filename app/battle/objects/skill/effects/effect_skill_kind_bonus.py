from typing import TYPE_CHECKING, ClassVar

from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.models import SkillEffectBase

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_stats import CombatStats


class _StackStyleBonusBase(SkillEffectBase):
    """적층형 버프/디버프를 쓰는 캐릭터와 쓰지 않는 캐릭터에게 서로 다른
    보정을 주는 효과의 공통 부모.

    걸려 있는 동안 유지되는 상태라 필드 효과·부적에서 쓴다. 값은 대상의
    CombatStats에 얹고, 실제 반영은 스택을 더하는 버프 부여 지점
    (BuffContainer.add)과 대미지 계산기 생성 시점(command_calculator)이 한다.
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


class SkillEffectExtraStackBonus(_StackStyleBonusBase):
    """대상이 적층형 버프/디버프를 부여할 때마다 `value_N`스택을 더 쌓는다.
    스킬·패시브·아이템 등 부여 경로를 가리지 않는다."""

    def apply_standing_state(self, stats: "CombatStats", *, revert: bool) -> None:
        stats.set_extra_stack_bonus(self.value or 0, revert=revert)


class SkillEffectNonStackerDamageBonus(_StackStyleBonusBase):
    """적층형 버프/디버프를 쓰는 스킬·패시브가 하나도 없는 캐릭터는 주는
    대미지가 `value_N`% 증가한다(BattlefieldContext.uses_stacking_buffs()).
    기본 공격과 스킬에 붙고, 아이템과 반격 같은 파생 대미지, "고정" 대미지에는
    붙지 않는다."""

    def apply_standing_state(self, stats: "CombatStats", *, revert: bool) -> None:
        stats.set_non_stacker_damage_bonus(self.value or 0, revert=revert)


# 시트의 effect_N 값을 새 이름으로 바꾸기 전까지 옛 이름도 읽히게 둔다.
# 배포 직후 시트를 고치기 전에 봇이 재기동하면 클래스를 못 찾아 기동이 실패한다.
SkillEffectStackSkillBonus = SkillEffectExtraStackBonus
SkillEffectPlainSkillDamageBonus = SkillEffectNonStackerDamageBonus
