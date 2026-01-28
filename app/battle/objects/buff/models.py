import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Type

from battle.objects.buff.conditions import Condition
from battle.objects.buff.define import BuffDurationType, BuffValueType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.objects.buff.buff_base import BuffBase


@dataclass
class BuffData:
    # 클래스 명칭과 동일
    buff_name: str

    # 지속 시간 (턴수 or 횟수)
    duration_type: BuffDurationType
    duration_value: int

    # 값 (정수 or 퍼센트, 보너스)
    value_type: Optional[BuffValueType] = None
    value: int = 0

    # 적용 조건
    condition_: Optional[str] = None
    condition_value: Optional[int] = None

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
        buff_class: Type["BuffBase"] = getattr(buff_module, self.buff_name)
        return buff_class(given_by=given_by, applied_to=applied_to, data=self)
