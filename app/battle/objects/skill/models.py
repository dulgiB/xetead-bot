import abc
import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Type

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import (
    MAX_EFFECT_COUNT,
    BattlefieldColumnIndex,
    SkillTargetOverrideType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.target_functions import SkillTargetRule
from utils.spreadsheet_bool import parse_spreadsheet_bool

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.conditions import Condition


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
    # 적층형 버프 부여/제거 시 한 번에 적용할 스택 상한
    buff_stack_cap: Optional[int] = None
    # 일반(버프) 조건: eager하게 즉시 평가 가능한 Condition. "ConsumedBuffStackCountCondition"
    # (스킬 조건)은 파싱 시점에 gate_value_source/gate_value로 변환되므로 여기 남지 않는다.
    condition_class_name: Optional[str] = None
    condition_value: Optional[int] = None
    # 스킬 조건(ConsumedBuffStackCountCondition) 전용 지연 게이트. 커맨드 처리
    # 중간값(같은 커맨드에서 지금까지 소모된 스택 합 등)에 의존해 expand() 시점엔
    # 평가할 수 없으므로 BuffAddData에 실어 CommandPartCalculator._buff_add_gate_passes()에서 판정한다.
    gate_value_source: Optional[ValueSourceType] = None
    gate_value: Optional[int] = None
    # 다른 버프의 id를 참조해야 하는 효과 전용(예: holder가 보유한 다른 버프의
    # 스택 수를 새 버프의 수치로 스냅샷). BuffData.reference_buff_id와 동일한 목적.
    reference_buff_id: Optional[str] = None
    # 대상이 이미 보유하고 있어야 하는 버프 id(선행 디버프 존재를 요구하는
    # 콤보용 게이트). buff_id(이 효과가 부여/조회하는 버프)와는 별개다.
    required_target_buff_id: Optional[str] = None

    @property
    def condition(self) -> Optional["Condition"]:
        if not self.condition_class_name:
            return None
        condition_module = importlib.import_module("battle.objects.buff.conditions")
        condition_class: Type["Condition"] = getattr(
            condition_module, self.condition_class_name
        )
        return condition_class(value=self.condition_value)

    @abc.abstractmethod
    def _expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
        raw_targets: "tuple[CharacterId | BattlefieldColumnIndex, ...]" = (),
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
        list[BuffRemoveData],
    ]:
        pass

    def expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
        raw_targets: "tuple[CharacterId | BattlefieldColumnIndex, ...]" = (),
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
        list[BuffRemoveData],
    ]:
        if self.target_override is None:
            return self._expand(context, holder, targets, raw_targets)

        if self.target_override == SkillTargetOverrideType.SELF:
            return self._expand(context, holder, [holder], raw_targets)

        raise ValueError(self.target_override)

    def get_debuff_clear_targets(
        self,
        context: "BattlefieldContext",
        targets: list[CharacterId],
    ) -> list[CharacterId]:
        """디버프를 일괄 제거하는 효과(SkillEffectRemoveDebuffs)만 오버라이드한다.

        expand() 호출 **전에** 불러야 한다 — expand()가 즉시 디버프를 지우므로,
        "무엇이 지워질지"는 지우기 전에 확정해야 답글에 정확히 표시할 수 있다.
        기본 구현은 대부분의 효과에 해당 사항이 없으므로 빈 리스트를 반환한다.
        """
        return []


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
        if data.get(f"value_source_{index}")
        else None
    )
    value = data.get(f"value_{index}") or None
    value_type = (
        SkillValueType(data[f"value_type_{index}"])
        if data.get(f"value_type_{index}")
        else None
    )
    # 스킬_캐릭터/스킬_패시브는 buff_id_{index}, 스킬_에너미는 buff_name_{index}를 쓴다.
    buff_id = data.get(f"buff_id_{index}") or data.get(f"buff_name_{index}") or None
    buff_add_timing = (
        RoundPhaseType(data[f"buff_add_timing_{index}"])
        if data.get(f"buff_add_timing_{index}")
        else None
    )
    target_override = (
        SkillTargetOverrideType(data[f"target_override_{index}"])
        if data.get(f"target_override_{index}")
        else None
    )
    apply_timing_raw = data.get(f"effect_apply_timing_{index}")
    apply_timing = RoundPhaseType(apply_timing_raw) if apply_timing_raw else None
    buff_stack_cap = (
        int(data[f"buff_stack_cap_{index}"])
        if data.get(f"buff_stack_cap_{index}")
        else None
    )

    condition_class_name = data.get(f"condition_{index}") or None
    condition_value = (
        int(data[f"condition_value_{index}"])
        if data.get(f"condition_value_{index}")
        else None
    )
    gate_value_source: Optional[ValueSourceType] = None
    gate_value: Optional[int] = None
    if condition_class_name == "ConsumedBuffStackCountCondition":
        # 스킬 조건: 커맨드 처리 중간값에만 의존하므로 일반 Condition으로 두지
        # 않고 기존 게이트 파이프라인(BuffAddData.gate_value_source/gate_value)으로 변환한다.
        gate_value_source = ValueSourceType.CONSUMED_BUFF_STACK
        gate_value = condition_value
        condition_class_name = None
        condition_value = None

    reference_buff_id = data.get(f"reference_buff_id_{index}") or None
    required_target_buff_id = data.get(f"required_target_buff_id_{index}") or None

    return effect(
        value_source=value_source,
        value=value,
        value_type=value_type,
        buff_id=buff_id,
        buff_add_timing=buff_add_timing,
        target_override=target_override,
        apply_timing=apply_timing,
        buff_stack_cap=buff_stack_cap,
        condition_class_name=condition_class_name,
        condition_value=condition_value,
        gate_value_source=gate_value_source,
        gate_value=gate_value,
        reference_buff_id=reference_buff_id,
        required_target_buff_id=required_target_buff_id,
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
    # 에너미 스킬 전용: 아직 한 번도 선언된 적 없는 스킬의 설명을 답글에서
    # 블라인드 처리할지 여부. "스킬_에너미" 시트의 is_revealed 체크박스
    # 컬럼에서 온다. 컬럼이 없는 시트(스킬_캐릭터 등)는 항상 True(공개).
    revealed: bool = True

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
            revealed=parse_spreadsheet_bool(data.get("is_revealed", True)),
        )

    def to_skill_instance(
        self, context: "BattlefieldContext", holder: CharacterId
    ) -> Skill:
        target_rule_module = importlib.import_module(
            "battle.objects.skill.target_functions"
        )
        rule: Type[SkillTargetRule] = getattr(target_rule_module, self.target_rule)
        return Skill(target_rule=rule(context, holder), data=self)
