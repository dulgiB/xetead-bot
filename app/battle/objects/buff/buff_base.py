import abc
from dataclasses import dataclass
from typing import Literal, Optional

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_events import BuffEvent
from battle.objects.buff.models import BuffData
from battle.objects.define import BuffApplyTiming, BuffCountDeductCondition
from battle.objects.models import BuffUid, CharacterId


@dataclass(frozen=True, eq=True)
class BuffAddData:
    given_by: CharacterId
    applied_to: CharacterId
    buff_id: str

    # 에너미 커맨드는 나눠서 처리하기 때문에 선행 버프와 후행 버프가 있음
    add_timing: Optional[
        Literal[RoundPhaseType.ENEMY_PRE_ACTION, RoundPhaseType.ENEMY_POST_ACTION]
    ] = None


class BuffDurationCounter:
    def __init__(
        self,
        duration_turn_value: Optional[int],
        duration_count_value: Optional[int],
        count_deduct_condition: Optional[BuffCountDeductCondition],
    ):
        self.remaining_turns = duration_turn_value
        self.remaining_count = duration_count_value
        self.count_deduct_condition = count_deduct_condition

    @property
    def is_passive(self) -> bool:
        return self.remaining_turns is None and self.remaining_count is None

    def deduct_turn(self):
        if self.remaining_turns is not None:
            self.remaining_turns -= 1

    def deduct_count(self, condition: BuffCountDeductCondition):
        if (
            self.remaining_count is not None
            and condition == self.count_deduct_condition
        ):
            self.remaining_count -= 1

    @property
    def finished(self) -> bool:
        if self.is_passive:
            return False
        elif self.remaining_turns is not None and self.remaining_count is not None:
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
        self.id = data.id
        self.uid = BuffUid(
            given_by,
            applied_to,
            data.buff_class_name,
        )

        self.given_by = given_by
        self.applied_to = applied_to

        # 값은 버프 생성 시점에 정해져서 이후 변동되지 않는다.
        self.value = data.value
        self.value_type = data.value_type

        self.duration = BuffDurationCounter(
            data.duration_turn_value,
            data.duration_count_value,
            data.duration_count_deduct_condition,
        )
        self.condition = data.condition

    def __hash__(self):
        return hash(self.uid)

    def get_target_override(self) -> Optional[CharacterId]:
        return None

    @property
    @abc.abstractmethod
    def timing(self) -> BuffApplyTiming:
        pass

    @abc.abstractmethod
    def create_event(self) -> BuffEvent:
        pass
