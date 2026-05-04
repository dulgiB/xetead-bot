import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Type

from battle.objects.buff.conditions import Condition
from battle.objects.buff.define import BuffDurationType
from battle.objects.define import ValueType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.objects.buff.buff_base import BuffBase


@dataclass
class BuffData:
    id: str
    buff_class_name: str

    # 지속 시간 (턴수 or 횟수)
    duration_type: BuffDurationType
    duration_value: int

    # 값 (정수 or 퍼센트, 보너스)
    value_type: Optional[ValueType]
    value: int

    # 적용 조건
    condition_: Optional[str]
    condition_value: Optional[int]

    @classmethod
    def from_dict(cls, data: dict[str, str | int]) -> "BuffData":
        return BuffData(
            id=data["id"],
            buff_class_name=data["buff_name"],
            duration_type=BuffDurationType(data["duration_type"]),
            duration_value=data["duration_value"],
            value_type=ValueType(data["value_type"]) if data["value_type"] else None,
            value=data["value"] if data["value_type"] else 0,
            condition_=data["condition"] if data["condition"] else None,
            condition_value=data["condition_value"]
            if data["condition_value"]
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

    def to_buff_instance(
        self, given_by: CharacterId, applied_to: CharacterId
    ) -> "BuffBase":
        buff_module = importlib.import_module("battle.objects.buff")
        buff_class: Type["BuffBase"] = getattr(buff_module, self.buff_class_name)
        return buff_class(given_by=given_by, applied_to=applied_to, data=self)
