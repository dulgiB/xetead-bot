import abc
import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Type

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.define import (
    MAX_EFFECT_COUNT,
    SkillTargetOverrideType,
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
    target_override: Optional[SkillTargetOverrideType] = None
    # 에너미 스킬 전용: 이 effect가 어느 페이즈에 적용되는지 명시. None이면 아군 스킬 동작(페이즈별 기본값 사용).
    apply_timing: Optional[
        Literal[RoundPhaseType.ENEMY_PRE_ACTION, RoundPhaseType.ENEMY_POST_ACTION]
    ] = None

    @abc.abstractmethod
    def _expand(
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
        if self.target_override is None:
            return self._expand(context, holder, targets)

        if self.target_override == SkillTargetOverrideType.SELF:
            return self._expand(context, holder, [holder])

        raise ValueError(self.target_override)


def parse_skill_effect(
    data: dict[str, str | int], index: int
) -> Optional[SkillEffectBase]:
    """스프레드시트 행에서 index번째 효과(effect_{index} 등)를 파싱한다.

    스킬(effect_0~2)과 아이템(effect_0) 양쪽에서 재사용된다.
    effect_{index} 컬럼이 비어 있으면 None을 반환한다.
    """
    effect_name = data.get(f"effect_{index}")
    if not effect_name:
        return None

    skill_effect_module = importlib.import_module("battle.objects.skill.effects")
    effect: Type[SkillEffectBase] = getattr(skill_effect_module, effect_name)

    value_source = (
        ValueSourceType(data[f"value_source_{index}"])
        if data[f"value_source_{index}"]
        else None
    )
    value = data[f"value_{index}"] if data[f"value_{index}"] else None
    value_type = (
        SkillValueType(data[f"value_type_{index}"])
        if data[f"value_type_{index}"]
        else None
    )
    buff_name = data[f"buff_name_{index}"] if data[f"buff_name_{index}"] else None
    buff_add_timing = (
        RoundPhaseType(data[f"buff_add_timing_{index}"])
        if data[f"buff_add_timing_{index}"]
        else None
    )
    target_override = (
        SkillTargetOverrideType(data[f"target_override_{index}"])
        if data.get(f"target_override_{index}")
        else None
    )
    apply_timing_raw = data.get(f"effect_apply_timing_{index}")
    apply_timing = RoundPhaseType(apply_timing_raw) if apply_timing_raw else None

    return effect(
        value_source=value_source,
        value=value,
        value_type=value_type,
        buff_id=buff_name,
        buff_add_timing=buff_add_timing,
        target_override=target_override,
        apply_timing=apply_timing,
    )


@dataclass(frozen=True)
class Skill:
    target_rule: SkillTargetRule
    data: "SkillData"


@dataclass(frozen=True)
class SkillData:
    id: str
    target_rule: str
    target_count: int
    cost: int
    effects: list[SkillEffectBase]
    description: str

    @classmethod
    def from_dict(cls, data: dict[str, str | int]) -> "SkillData":
        skill_effects: list[SkillEffectBase] = []

        for i in range(MAX_EFFECT_COUNT):
            if (effect := parse_skill_effect(data, i)) is not None:
                skill_effects.append(effect)

        return SkillData(
            id=data["id"],
            target_rule=data["target_rule"],
            target_count=data["target_count"],
            cost=data["cost"],
            effects=skill_effects,
            description=data["description"],
        )

    def to_skill_instance(
        self, context: "BattlefieldContext", holder: CharacterId
    ) -> Skill:
        target_rule_module = importlib.import_module(
            "battle.objects.skill.target_functions"
        )
        rule: Type[SkillTargetRule] = getattr(target_rule_module, self.target_rule)
        return Skill(target_rule=rule(context, holder), data=self)
