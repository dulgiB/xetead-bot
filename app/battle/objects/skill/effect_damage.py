from typing import TYPE_CHECKING

from battle.objects.skill.models import SkillEffectBase
from utils.dice import nd6

if TYPE_CHECKING:
    from battle.objects.character.combat_character import CombatCharacter


class SkillEffectDamage(SkillEffectBase):
    def _apply(
        self, holder: "CombatCharacter", target: "CombatCharacter", **kwargs
    ) -> None:
        pass
