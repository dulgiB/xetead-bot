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

    # None이면 적층 불가(재부여 시 스택 무시).
    max_stack: Optional[int] = None

    # 다른 버프의 id를 참조하는 효과(스택 수 기반 대미지 등) 전용.
    reference_buff_id: Optional[str] = None

    # 두 번째 수치가 필요한 버프 전용. value/value_type과 논리적으로 한 쌍이지만
    # dataclass 필드 순서 제약 때문에 물리적으로는 끝에 온다. 값의 해석(퍼센트/
    # 정수)은 각 버프 클래스가 고정으로 정한다.
    # 시트 컬럼명은 value_1이고 필드명만 value_2다(buff_name/buff_class_name과
    # 동일한 시트-필드명 불일치 관례).
    value_2: int = 0

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
            value_type=ValueType(data["value_type_0"])
            if data["value_type_0"]
            else None,
            value=int(data["value_0"]) if data["value_type_0"] else 0,
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
            value_2=int(data["value_1"]) if data.get("value_1") else 0,
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
    # BuffData.value_2와 동일(시트 컬럼명도 동일하게 value_1).
    value_2: int = 0

    @classmethod
    def from_dict(cls, data: SpreadsheetRow) -> "PassiveBuffData":
        return cls(
            id=str(data["id"]),
            buff_class_name=str(data["buff_name"]),
            value=int(data["value_0"]) if data.get("value_0") else 0,
            value_type=ValueType(data["value_type_0"])
            if data.get("value_type_0")
            else None,
            condition_=str(data["condition"]) if data.get("condition") else None,
            condition_value=int(data["condition_value"])
            if data.get("condition_value")
            else None,
            description=str(data.get("description", "")),
            reference_buff_id=str(data["reference_buff_id"])
            if data.get("reference_buff_id")
            else None,
            value_2=int(data["value_1"]) if data.get("value_1") else 0,
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
