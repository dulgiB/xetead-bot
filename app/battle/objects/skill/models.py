import abc
import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Type

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import (
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.target_functions import SkillTargetRule

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class SkillEffectBase(abc.ABC):
    value_source: Optional[ValueSourceType]
    value: Optional[int]
    value_type: Optional[ValueType]
    buff_id: Optional[str]
    buff_add_timing: Optional[
        Literal[RoundPhaseType.ENEMY_PRE_ACTION, RoundPhaseType.ENEMY_POST_ACTION]
    ]

    @abc.abstractmethod
    def expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
    ]:
        pass


@dataclass(frozen=True)
class Skill:
    target_rule: SkillTargetRule
    data: "SkillData"


@dataclass(frozen=True)
class SkillData:
    id: str
    target_rule: str
    cost: int
    effects: list[SkillEffectBase]

    @classmethod
    def from_dict(cls, data: dict[str, str | int]) -> "SkillData":
        skill_effects: list[SkillEffectBase] = []
        skill_effect_module = importlib.import_module("battle.objects.skill.effects")

        for i in range(3):
            if effect_name := data.get(f"effect_{i}"):
                effect: Type[SkillEffectBase] = getattr(
                    skill_effect_module, effect_name
                )
                value_source = (
                    ValueSourceType(data[f"value_source_{i}"])
                    if data[f"value_source_{i}"]
                    else None
                )
                value = data[f"value_{i}"] if data[f"value_{i}"] else None
                value_type = (
                    SkillValueType(data[f"value_type_{i}"])
                    if data[f"value_type_{i}"]
                    else None
                )
                buff_name = data[f"buff_name_{i}"] if data[f"buff_name_{i}"] else None
                buff_add_timing = (
                    RoundPhaseType(data[f"buff_add_timing_{i}"])
                    if data[f"buff_add_timing_{i}"]
                    else None
                )

                skill_effects.append(
                    effect(
                        value_source=value_source,
                        value=value,
                        value_type=value_type,
                        buff_id=buff_name,
                        buff_add_timing=buff_add_timing,
                    )
                )

        return SkillData(
            id=data["id"],
            target_rule=data["target_rule"],
            cost=data["cost"],
            effects=skill_effects,
        )

    def to_skill_instance(
        self, context: "BattlefieldContext", holder: CharacterId
    ) -> Skill:
        target_rule_module = importlib.import_module(
            "battle.objects.skill.target_functions"
        )
        rule: Type[SkillTargetRule] = getattr(target_rule_module, self.target_rule)
        return Skill(target_rule=rule(context, holder), data=self)
