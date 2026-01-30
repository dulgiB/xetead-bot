import abc
from dataclasses import KW_ONLY, dataclass, field
from typing import TYPE_CHECKING, Optional

from battle.core.commands.models import DamageData, HealData, MoveData
from battle.exceptions import CommandValidationError, error_no_remaining_cost
from battle.objects.buff.buff_base import BuffBase
from battle.objects.define import (
    ActionType,
    CombatStatType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import BuffId, CharacterId
from battle.objects.skill.target_functions import (
    SkillTargetRule,
    SkillTargetRuleNamed,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_character import CombatCharacter


@dataclass(frozen=True)
class SkillEffectBase(abc.ABC):
    value_source: Optional[ValueSourceType]
    value: Optional[int]
    value_type: Optional[ValueType]
    buff_id: Optional[str]


@dataclass(frozen=True)
class SkillData:
    id: int
    skill_type: ActionType
    cost: int
    effects: list[SkillEffectBase]
