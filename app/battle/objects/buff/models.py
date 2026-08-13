import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Type

from battle.objects.buff.conditions import Condition
from battle.objects.define import BuffCountDeductCondition, ValueType
from battle.objects.models import CharacterId
from utils.spreadsheet_bool import parse_spreadsheet_bool
from utils.spreadsheet_row import SpreadsheetRow

if TYPE_CHECKING:
    from battle.objects.buff.buff_base import BuffBase


@dataclass
class BuffData:
    id: str
    buff_class_name: str

    duration_turn_value: Optional[int]
    duration_count_value: Optional[int]
    duration_count_deduct_condition: Optional[BuffCountDeductCondition]

    value_type: Optional[ValueType]
    value: int

    condition_: Optional[str]
    condition_value: Optional[int]

    # 디버프 여부 — TargetHasDebuffCondition에서 사용
    is_debuff: bool

    description: str

    # 최대 적층 스택 수. None이면 적층 불가(재부여 시 무시, 기존 동작 유지).
    max_stack: Optional[int] = None

    # 다른 버프의 id를 참조해야 하는 효과(스택 수 기반 대미지 등) 전용.
    # 참조 대상이 없는 대부분의 버프에는 쓰이지 않는다.
    reference_buff_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: SpreadsheetRow) -> "BuffData":
        return BuffData(
            id=str(data["id"]),
            buff_class_name=str(data["buff_name"]),
            duration_turn_value=int(data["duration_turn_value"])
            if data["duration_turn_value"]
            else None,
            duration_count_value=int(data["duration_count_value"])
            if data["duration_count_value"]
            else None,
            duration_count_deduct_condition=BuffCountDeductCondition(
                data["duration_count_deduct_condition"]
            )
            if data["duration_count_deduct_condition"]
            else None,
            value_type=ValueType(data["value_type"]) if data["value_type"] else None,
            value=int(data["value"]) if data["value_type"] else 0,
            condition_=str(data["condition"]) if data["condition"] else None,
            condition_value=int(data["condition_value"])
            if data["condition_value"]
            else None,
            is_debuff=parse_spreadsheet_bool(data.get("is_debuff", False)),
            description=str(data["description"]),
            max_stack=int(data["max_stack"]) if data.get("max_stack") else None,
            reference_buff_id=str(data["reference_buff_id"])
            if data.get("reference_buff_id")
            else None,
        )

    @property
    def condition(self) -> Optional[Condition]:
        if self.condition_:
            condition_module = importlib.import_module("battle.objects.buff.conditions")
            condition_class: Type[Condition] = getattr(
                condition_module, self.condition_
            )
            return condition_class(value=self.condition_value)
        return None

    def get_buff_class(self) -> Type["BuffBase"]:
        buff_module = importlib.import_module("battle.objects.buff.buffs")
        return getattr(buff_module, self.buff_class_name)

    def to_buff_instance(
        self,
        given_by: CharacterId,
        applied_to: CharacterId,
        initial_stack: int = 1,
        value_override: Optional[int] = None,
    ) -> "BuffBase":
        buff_class = self.get_buff_class()
        return buff_class(
            given_by=given_by,
            applied_to=applied_to,
            data=self,
            initial_stack=initial_stack,
            value_override=value_override,
        )


@dataclass
class PassiveBuffData:
    """'버프_패시브' 시트 전용 축소판 버프 데이터. 패시브 스킬이 기존 버프
    이벤트를 그대로 재사용하는 "버프 모디파이어 경로"에서만 쓰인다 — 지속시간/
    디버프 여부/적층 개념이 없는, 항상 켜져 있는 수정자이기 때문이다."""

    id: str
    buff_class_name: str
    value: int
    value_type: Optional[ValueType]
    condition_: Optional[str]
    condition_value: Optional[int]
    description: str
    # BuffData.reference_buff_id와 동일한 목적(다른 버프 id 참조).
    reference_buff_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: SpreadsheetRow) -> "PassiveBuffData":
        return cls(
            id=str(data["id"]),
            buff_class_name=str(data["buff_name"]),
            value=int(data["value"]) if data.get("value") else 0,
            value_type=ValueType(data["value_type"])
            if data.get("value_type")
            else None,
            condition_=str(data["condition"]) if data.get("condition") else None,
            condition_value=int(data["condition_value"])
            if data.get("condition_value")
            else None,
            description=str(data.get("description", "")),
            reference_buff_id=str(data["reference_buff_id"])
            if data.get("reference_buff_id")
            else None,
        )

    @property
    def condition(self) -> Optional[Condition]:
        if self.condition_:
            condition_module = importlib.import_module("battle.objects.buff.conditions")
            condition_class: Type[Condition] = getattr(
                condition_module, self.condition_
            )
            return condition_class(value=self.condition_value)
        return None
