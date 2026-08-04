import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Self

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_events import BuffEvent
from battle.objects.buff.conditions import Condition
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    BuffApplyTiming,
    BuffCountDeductCondition,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import BuffUid, CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.commands.models import BattleLogEntry


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

    # 버프 시트의 고정 value 대신 이 값을 쓴다. 부여 시점에 계산한 수치를
    # 그 버프의 수치에 그대로 스냅샷해야 하는 경우 전용(예: 다른 버프의
    # 현재 스택 수 × 계수). None이면 버프 시트의 value를 그대로 쓴다.
    value_override: Optional[int] = None


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

    def display_text(self, stack_count: Optional[int] = None) -> str:
        """ "(N턴/M회)" 또는 "(N턴/M스택)" 형식의 표시 텍스트.

        stack_count는 적층형 버프(max_stack이 있는 버프)에 한해 호출측이
        넘긴다. 구조상 적층형 버프는 duration_count_value(횟수)를 쓰지
        않으므로 M회/M스택이 함께 나타나는 경우는 없다. 아무 것도 표시할
        내용이 없으면(패시브 + 비적층) 빈 문자열."""
        parts = []
        if self.remaining_turns is not None:
            parts.append(f"{self.remaining_turns}턴")
        if self.remaining_count is not None:
            parts.append(f"{self.remaining_count}회")
        if stack_count is not None:
            parts.append(f"{stack_count}스택")
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

        # 다른 버프의 id를 참조해야 하는 효과 전용(대부분의 버프는 쓰지 않음).
        self.reference_buff_id = data.reference_buff_id

    @classmethod
    def _create_bare(
        cls,
        *,
        id_: str,
        uid: BuffUid,
        given_by: CharacterId,
        applied_to: CharacterId,
        value: int = 0,
        value_type: Optional[ValueType] = None,
        condition: Optional[Condition] = None,
        reference_buff_id: Optional[str] = None,
    ) -> Self:
        """ "버프" 시트의 BuffData 없이 필드를 직접 채워 인스턴스화한다
        (__init__은 BuffData를 요구하므로 우회 경로가 필요한 곳 전용 —
        패시브 스킬 래퍼, 패시브 버프 모디파이어 값 템플릿). BuffBase에
        필드가 추가되면 이 메서드 하나만 맞추면 된다."""
        obj = object.__new__(cls)
        obj.id = id_
        obj.uid = uid
        obj.given_by = given_by
        obj.applied_to = applied_to
        obj.value = value
        obj.value_type = value_type
        obj.duration = BuffDurationCounter(None, None, None)
        obj.condition = condition
        obj.is_debuff = False
        obj.max_stack = None
        obj.stack_count = 1
        obj.reference_buff_id = reference_buff_id
        return obj

    def __hash__(self):
        return hash(self.uid)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BuffBase):
            return NotImplemented
        return self.uid == other.uid

    def get_target_override(self) -> Optional[CharacterId]:
        return None

    def display_id_label(self) -> str:
        """버프 표시용 id 라벨. 기본은 id 그대로. 부여자에 따라 대상이
        달라지는 버프(도발 등)는 오버라이드해서 부여자 이름을 덧붙인다."""
        return self.id

    def get_description(self, context: "BattlefieldContext") -> str:
        """버프 설명 텍스트. 기본은 "버프" 시트에서 id로 조회. 시트에
        등록되지 않은 버프(패시브 스킬 래핑 등)는 오버라이드해야 한다."""
        return context.get_buff_data_by_id(self.id).description

    def get_sacrifice_override(self) -> Optional[CharacterId]:
        return None

    def on_battle_end(
        self, context: "BattlefieldContext"
    ) -> Optional["BattleLogEntry"]:
        """전투 종료 시점에 호출된다. 정산 결과(HP 변동 등)가 있으면
        전투 종료 답글에 표시할 BattleLogEntry를 반환한다. 기본은 아무
        동작도 하지 않는다."""
        return None

    @property
    @abc.abstractmethod
    def timing(self) -> BuffApplyTiming:
        pass

    @abc.abstractmethod
    def create_event(self) -> BuffEvent:
        pass
