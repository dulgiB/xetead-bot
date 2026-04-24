import abc
from dataclasses import dataclass

from battle.objects.buff.buff_events import BuffEvent
from battle.objects.buff.define import BuffDurationType
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    BuffApplyTiming,
)
from battle.objects.models import (
    BuffId,
    CharacterId,
)


@dataclass(frozen=True, eq=True)
class BuffAddData:
    given_by: CharacterId
    applied_to: CharacterId
    buff_name: str


class BuffDurationCounter:
    def __init__(self, duration_type: BuffDurationType, duration_value: int):
        self.remaining_turns = (
            duration_value if duration_type == BuffDurationType.TURN else None
        )
        self.remaining_count = (
            duration_value if duration_type == BuffDurationType.COUNT else None
        )

    def deduct_turn(self):
        if self.remaining_turns is not None:
            self.remaining_turns -= 1

    def deduct_count(self):
        if self.remaining_count is not None:
            self.remaining_count -= 1

    @property
    def finished(self) -> bool:
        if self.remaining_turns is not None and self.remaining_count is not None:
            return self.remaining_turns == 0 and self.remaining_count == 0
        elif self.remaining_turns is not None:
            return self.remaining_turns == 0
        elif self.remaining_count is not None:
            return self.remaining_count == 0
        return True


class BuffBase(abc.ABC):
    def __init__(
        self,
        given_by: CharacterId,
        applied_to: CharacterId,
        data: BuffData,
    ):
        self.id = BuffId(
            given_by,
            applied_to,
            data.buff_name,
        )

        self.given_by = given_by
        self.applied_to = applied_to

        # 값은 버프 생성 시점에 정해져서 이후 변동되지 않는다.
        self.value = data.value
        self.value_type = data.value_type

        self.duration = BuffDurationCounter(data.duration_type, data.duration_value)
        self.condition = data.condition

    def __hash__(self):
        return hash(self.id)

    @property
    @abc.abstractmethod
    def timing(self) -> set[BuffApplyTiming]:
        pass

    @abc.abstractmethod
    def create_event(self) -> BuffEvent:
        pass
