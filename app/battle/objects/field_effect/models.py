from dataclasses import dataclass
from enum import Enum
from typing import Optional

from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData

# 필드 효과의 홀더 id에 붙는 접두사. 전장에 실제로 존재하는 캐릭터 이름과
# 절대 겹치지 않아야 한다 — 겹치면 그 캐릭터가 필드 효과의 홀더로 잡힌다.
_HOLDER_ID_PREFIX = "__field__"


def field_effect_holder_id(effect_id: str) -> CharacterId:
    """필드 효과가 버프를 부여할 때 given_by로 쓸 센티넬 홀더 id.

    필드 효과는 캐릭터가 아니라 전장에 붙으므로 홀더가 될 캐릭터가 없다.
    그래도 홀더 자리를 비워 둘 수는 없어서(BuffBase가 given_by/applied_to를
    요구한다) 전장에 존재하지 않는 id를 쓴다. **효과마다 고유해야 한다** —
    제거할 때 given_by로 자기가 부여한 버프만 골라 걷기 때문이다.
    """
    return CharacterId(f"{_HOLDER_ID_PREFIX}{effect_id}")


def is_field_effect_holder(char_id: CharacterId) -> bool:
    """이 id가 필드 효과의 센티넬 홀더인지. 전장에 없는 공격자/부여자를
    "죽은 캐릭터"로 오해하고 버리지 않으려면 대미지 파이프라인이 이 둘을
    구분할 수 있어야 한다."""
    return char_id.name.startswith(_HOLDER_ID_PREFIX)


class FieldEffectSource(str, Enum):
    """이 필드 효과가 어떻게 전장에 올라왔는지. 답글·필드 시트 표시용이며,
    제거 권한을 가르지는 않는다 — 어느 출처든 admin이 해제할 수 있다.

    admin을 "시스템"이라 적는 것은 게임 안에서 admin의 행동을 부르는 기존
    이름과 맞추기 위해서다(commands/admin.py의 ADMIN_ID).
    """

    SKILL = "스킬"
    ADMIN = "시스템"


@dataclass(frozen=True)
class FieldEffectOp:
    """스킬이 선언한 필드 효과 부여/해제 요청.

    전개(expand) 시점에는 요청만 만들고 실제 반영은 처리 시점에 한다 —
    커맨드가 검증에서 막히면 전장이 바뀌면 안 되고, 답글에 무엇이 일어났는지
    적으려면 처리 결과가 필요하기 때문이다.
    """

    effect_id: str
    remove: bool = False
    # 부여 요청에만 쓴다.
    turns: Optional[int] = None


@dataclass(frozen=True)
class FieldEffect:
    """전장 전체에 걸린 효과. 캐릭터가 아니라 BattlefieldContext에 붙는다.

    효과 본체는 "스킬_패시브" 시트의 PassiveSkillData를 그대로 재사용하며,
    필드 범위 target_type(FIELD_SCOPE_TARGET_TYPES)이 그 행을 캐릭터
    패시브가 아닌 필드 효과로 구분한다.

    `remaining_turns`가 None이면 해제 전까지 유지되는 상시 효과이고, 값이
    있으면 버프처럼 라운드 종료마다 1씩 줄다가 0이 되면 걷히는 일시 효과다.
    턴 수를 효과 행이 아니라 거는 쪽이 정하는 것은 같은 효과를 admin은
    상시로, 스킬은 몇 턴만 걸 수 있게 하기 위해서다.
    """

    data: PassiveSkillData
    source: FieldEffectSource
    # 출처를 사람이 읽을 수 있게 덧붙이는 꼬리표(시전자 이름 등).
    # 비어 있으면 표시에서 생략한다.
    source_detail: str = ""
    remaining_turns: Optional[int] = None

    @property
    def id(self) -> str:
        return self.data.id

    @property
    def holder_id(self) -> CharacterId:
        return field_effect_holder_id(self.data.id)

    @property
    def description(self) -> str:
        return self.data.description

    @property
    def is_temporary(self) -> bool:
        return self.remaining_turns is not None

    def display_label(self) -> str:
        """`이름[출처]` 형태의 표시 라벨.

        대괄호 안은 출처를 특정할 수 있으면 그 이름, 아니면 출처 종류다 —
        누가 걸었는지가 종류보다 쓸모 있는 정보다.
        """
        label = f"{self.id}[{self.source_detail or self.source.value}]"
        return label + format_field_effect_turns(self.remaining_turns)


def format_field_effect_turns(turns: Optional[int]) -> str:
    return "" if turns is None else f" ({turns}턴)"
