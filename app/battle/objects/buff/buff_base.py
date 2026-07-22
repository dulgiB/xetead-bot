import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_events import BuffEvent
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    BuffApplyTiming,
    BuffCountDeductCondition,
    ValueSourceType,
)
from battle.objects.models import BuffUid, CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True, eq=True)
class BuffAddData:
    given_by: CharacterId
    applied_to: CharacterId
    buff_id: str

    # 에너미 커맨드는 나눠서 처리하기 때문에 선행 버프와 후행 버프가 있음
    add_timing: Optional[
        Literal[RoundPhaseType.ENEMY_PRE_ACTION, RoundPhaseType.ENEMY_POST_ACTION]
    ] = None

    # 적층형 버프에 한 번에 더할 스택 수 (max_stack이 없는 버프에는 영향 없음)
    stack_value: int = 1

    # 조건부 부여 게이트: gate_value_source가 설정돼 있으면 처리 시점에
    # (CONSUMED_BUFF_STACK 등으로 계산한) 값이 gate_value 미만일 때 부여를 건너뛴다.
    gate_value_source: Optional[ValueSourceType] = None
    gate_value: Optional[int] = None


@dataclass(frozen=True, eq=True)
class BuffRemoveData:
    """적층형 버프의 스택을 일부 제거 요청한다. 즉시 mutate하지 않고 선언적으로
    보관되며, 실제 제거는 CommandPartCalculator.process() 시점에 이뤄진다."""

    applied_to: CharacterId
    buff_id: str
    requested_amount: int


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
            return self.remaining_turns == 0 or self.remaining_count == 0
        elif self.remaining_turns is not None:
            return self.remaining_turns == 0
        elif self.remaining_count is not None:
            return self.remaining_count == 0
        return True

    def display_text(self) -> str:
        """"(N턴/M회)" 형식의 표시 텍스트. 패시브(영구)면 빈 문자열."""
        if self.is_passive:
            return ""
        parts = []
        if self.remaining_turns is not None:
            parts.append(f"{self.remaining_turns}턴")
        if self.remaining_count is not None:
            parts.append(f"{self.remaining_count}회")
        return f" ({'/'.join(parts)})" if parts else ""


class BuffBase(abc.ABC):
    def __init__(
        self,
        given_by: CharacterId,
        applied_to: CharacterId,
        data: BuffData,
        initial_stack: int = 1,
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
        self.is_debuff = data.is_debuff

        # 적층(스택) 지원. max_stack이 None이면 적층 불가 버프(기존 동작과 동일).
        self.max_stack = data.max_stack
        self.stack_count = initial_stack

    def __hash__(self):
        return hash(self.uid)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BuffBase):
            return NotImplemented
        return self.uid == other.uid

    def get_target_override(self) -> Optional[CharacterId]:
        return None

    def get_sacrifice_override(self) -> Optional[CharacterId]:
        return None

    def on_battle_end(self, context: "BattlefieldContext") -> None:
        """전투 종료 시점에 호출된다. 기본은 아무 동작도 하지 않는다."""
        pass

    @property
    @abc.abstractmethod
    def timing(self) -> BuffApplyTiming:
        pass

    @abc.abstractmethod
    def create_event(self) -> BuffEvent:
        pass
