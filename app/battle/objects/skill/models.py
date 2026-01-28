import abc
from dataclasses import KW_ONLY, dataclass, field
from typing import TYPE_CHECKING, Optional

from battle.core.commands.models import DamageData, HealData, MoveData
from battle.exceptions import CommandValidationError, error_no_remaining_cost
from battle.objects.buff.buff_base import BuffBase
from battle.objects.define import (
    ActionType,
    CombatStatType,
)
from battle.objects.models import BuffId, CharacterId
from battle.objects.skill.target_functions import (
    SkillTargetRule,
    SkillTargetRuleNamed,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.character.combat_character import CombatCharacter


@dataclass
class SkillEffectApplyData:
    _: KW_ONLY
    move_data: list[MoveData] = field(default_factory=list)
    damage_data: list[DamageData] = field(default_factory=list)
    heal_data: list[HealData] = field(default_factory=list)
    buff_add_data: list[BuffBase] = field(default_factory=list)
    buff_remove_data: list[BuffId] = field(default_factory=list)

    def __add__(self, other: "SkillEffectApplyData") -> "SkillEffectApplyData":
        return SkillEffectApplyData(
            move_data=self.move_data + other.move_data,
            damage_data=self.damage_data + other.damage_data,
            heal_data=self.heal_data + other.heal_data,
            buff_add_data=self.buff_add_data + other.buff_add_data,
            buff_remove_data=self.buff_remove_data + other.buff_remove_data,
        )


class SkillEffectBase(abc.ABC):
    def __init__(
        self,
        target_rule: SkillTargetRule,
        related_stat_1: Optional[CombatStatType] = None,
        related_stat_2: Optional[CombatStatType] = None,
        value_1: int | float | None = None,
        value_2: int | float | None = None,
    ):
        self.target_rule = target_rule

        self.related_stat_1 = related_stat_1
        self.related_stat_2 = related_stat_2
        self.value_1 = value_1
        self.value_2 = value_2

    @abc.abstractmethod
    def _apply(
        self,
        holder: "CombatCharacter",
        target: "CombatCharacter | None",
    ) -> SkillEffectApplyData:
        raise NotImplementedError

    def apply(
        self,
        context: "BattlefieldContext",
        holder: "CombatCharacter",
        targets: Optional[list[CharacterId]],
    ) -> SkillEffectApplyData:
        if isinstance(self.target_rule, SkillTargetRuleNamed):
            targets = [context.characters[target_id] for target_id in targets]
        else:
            targets = self.target_rule.get_targets()

        result = SkillEffectApplyData()
        for target in targets:
            result += self._apply(holder, target)

        return result


@dataclass
class SkillExecutionData:
    effect_data: list[SkillEffectApplyData]


@dataclass
class SkillBaseData(abc.ABC):
    id: int
    skill_type: ActionType
    cost: int
    effects: list[SkillEffectBase]

    @abc.abstractmethod
    def use(
        self,
        context: "BattlefieldContext",
        holder: "CombatCharacter",
        targets: list[CharacterId],
    ) -> SkillExecutionData:
        if self.cost > holder.status.remaining_cost:
            raise CommandValidationError(
                error_no_remaining_cost(
                    self.cost,
                    holder.status.remaining_cost,
                )
            )

        result: list[SkillEffectApplyData] = []
        for effect in self.effects:
            result.append(effect.apply(context, holder, targets))

        return SkillExecutionData(result)
