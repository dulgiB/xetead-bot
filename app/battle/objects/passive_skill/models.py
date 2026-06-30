import importlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Type

from battle.objects.buff.conditions import Condition
from battle.objects.define import ValueSourceType
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.models import SkillEffectBase


class PassiveSkillTrigger(str, Enum):
    ROUND_START = "라운드 시작"
    ON_ACTION = "행동 시"


class PassiveSkillTargetType(str, Enum):
    SELF = "자신"
    SAME_COLUMN_ALLIES = "같은 열 아군"
    ALL_ALLIES = "전체 아군"
    ATTACKER_OR_TARGET = "공격자_또는_대상"


@dataclass(frozen=True)
class PassiveSkillData:
    id: str
    trigger: PassiveSkillTrigger
    target_type: PassiveSkillTargetType
    effect: SkillEffectBase

    condition_class_name: Optional[str]
    condition_value: Optional[int]

    description: str

    @classmethod
    def from_dict(cls, data: dict) -> "PassiveSkillData":
        effect_module = importlib.import_module("battle.objects.skill.effects")
        effect_class: Type[SkillEffectBase] = getattr(effect_module, data["effect"])

        value_source = (
            ValueSourceType(data["value_source"]) if data.get("value_source") else None
        )
        value = int(data["value"]) if data.get("value") else None
        value_type = (
            SkillValueType(data["value_type"]) if data.get("value_type") else None
        )
        buff_id = data.get("buff_id") or None

        effect = effect_class(
            value_source=value_source,
            value=value,
            value_type=value_type,
            buff_id=buff_id,
            buff_add_timing=None,
            target_override=None,
            apply_timing=None,
        )

        return cls(
            id=data["id"],
            trigger=PassiveSkillTrigger(data["trigger"]),
            target_type=PassiveSkillTargetType(data["target_type"]),
            effect=effect,
            condition_class_name=data.get("condition") or None,
            condition_value=int(data["condition_value"])
            if data.get("condition_value")
            else None,
            description=data.get("description", ""),
        )

    @property
    def condition(self) -> Optional[Condition]:
        if not self.condition_class_name:
            return None
        module = importlib.import_module("battle.objects.buff.conditions")
        condition_class = getattr(module, self.condition_class_name)
        return condition_class(value=self.condition_value)
