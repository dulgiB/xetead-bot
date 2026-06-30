import importlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Type

from battle.objects.buff.buff_events import BuffEvent
from battle.objects.buff.conditions import Condition
from battle.objects.define import ValueSourceType, ValueType
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.models import SkillEffectBase


class PassiveSkillTrigger(str, Enum):
    ROUND_START = "라운드 시작"
    ON_ACTION = "행동 시"
    ON_ENEMY_MOVE = "적 이동 시"


class PassiveSkillTargetType(str, Enum):
    SELF = "자신"
    SAME_COLUMN_ALLIES = "같은 열 아군"
    ALL_ALLIES = "전체 아군"
    ATTACKER_OR_TARGET = "공격자_또는_대상"
    LOWEST_HP_ALLY = "체력 최저 아군"


@dataclass(frozen=True)
class PassiveSkillData:
    id: str
    trigger: PassiveSkillTrigger
    target_type: PassiveSkillTargetType
    effect: Optional[SkillEffectBase]
    condition_class_name: Optional[str]
    condition_value: Optional[int]
    description: str
    # Buff modifier 경로. effect 대신 사용하면 기존 계산에 수정자를 직접 주입한다.
    buff_mod_event: Optional[BuffEvent] = None

    @classmethod
    def from_dict(cls, data: dict) -> "PassiveSkillData":
        if data.get("buff_class_name"):
            # Buff modifier 경로: 임시 인스턴스로 BuffEvent 생성 후 저장
            buff_module = importlib.import_module("battle.objects.buff.buffs")
            buff_class = getattr(buff_module, data["buff_class_name"])
            temp = object.__new__(buff_class)
            temp.id = data.get("id", "")
            temp.value = int(data["value"]) if data.get("value") else 0
            value_type_str = data.get("value_type")
            temp.value_type = ValueType(value_type_str) if value_type_str else None
            temp.condition = None  # 조건은 PassiveSkillData.condition으로 처리
            buff_mod_event: Optional[BuffEvent] = temp.create_event()
            effect: Optional[SkillEffectBase] = None
        else:
            buff_mod_event = None
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
            buff_mod_event=buff_mod_event,
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
