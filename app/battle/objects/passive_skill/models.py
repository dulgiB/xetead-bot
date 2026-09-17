import importlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from battle.objects.buff.buff_events import BuffEvent
from battle.objects.buff.models import PassiveBuffData
from battle.objects.define import MAX_PASSIVE_EFFECT_COUNT, FactionType
from battle.objects.models import BuffUid, CharacterId
from battle.objects.skill.models import SkillEffectBase, parse_skill_effect
from utils.spreadsheet_row import SpreadsheetRow

# buff_mod_event 추출용 임시 인스턴스는 create_event()만 호출하고 버려지므로
# 실제 캐릭터가 필요 없다 — 데이터 로드 시점엔 전투 참가자도 아직 없다.
_TEMPLATE_CHARACTER_ID = CharacterId("__buff_mod_template__")


class PassiveSkillTrigger(str, Enum):
    BATTLE_START = "전투 시작"
    ROUND_START = "라운드 시작"
    ROUND_END = "라운드 종료"
    ON_ACTION = "행동 시"
    ON_ENEMY_MOVE = "적 이동 시"
    ENEMY_POST_ACTION = "적 후행 시"
    ALLY_DAMAGED = "아군 피격 시"
    ALLY_IN_RANGE_DAMAGED = "사거리 내 아군 피격 시"


class PassiveSkillTargetType(str, Enum):
    SELF = "자신"
    SAME_COLUMN_ALLIES = "같은 열 아군"
    SELF_AND_SAME_COLUMN_ALLIES = "자신을 포함한 같은 열 아군"
    SELF_AND_ADJACENT_COLUMN_ALLIES = "자신을 포함한 좌우 1열 아군"
    ALL_ALLIES = "전체 아군"
    ATTACKER_OR_TARGET = "공격자 또는 대상"
    LOWEST_HP_ALLY = "체력 최저 아군"

    # 필드 효과 전용. 위의 값들이 홀더를 기준으로 상대적인 범위를 잡는 것과
    # 달리, 이 넷은 홀더를 보지 않는다 — 필드 효과는 캐릭터가 아니라 전장에
    # 붙으므로 기준이 될 홀더가 없다. 앞의 셋은 진영을 절대 기준으로 지정하며,
    # 그래서 보스가 자기 진영을 강화하는 필드 효과는 FIELD_ENEMY_SIDE다.
    FIELD_ALLY_SIDE = "필드 아군 진영"
    FIELD_ENEMY_SIDE = "필드 적군 진영"
    FIELD_ALL = "필드 전원"
    # 반응형 트리거(이동 시·피격 시 등)에서 그 사건을 일으킨 당사자만 대상으로
    # 삼는다. 진영을 가리지 않으므로 양쪽 진영의 사건에 모두 반응한다.
    FIELD_SUBJECT = "필드 사건 당사자"


# 홀더 없이 해석되는 대상 범위. 필드 효과에 쓸 수 있는 값이자, 캐릭터
# 패시브에는 쓰면 안 되는 값이기도 하다(홀더 진영이 무시되므로).
FIELD_SCOPE_TARGET_TYPES: frozenset[PassiveSkillTargetType] = frozenset(
    {
        PassiveSkillTargetType.FIELD_ALLY_SIDE,
        PassiveSkillTargetType.FIELD_ENEMY_SIDE,
        PassiveSkillTargetType.FIELD_ALL,
        PassiveSkillTargetType.FIELD_SUBJECT,
    }
)

# 필드 범위 → 그 범위가 가리키는 진영. None이면 진영을 가리지 않는다.
# 대상을 고르는 데도, 반응형 트리거에서 "누구의 사건에 반응하는가"를 가리는
# 데도 같은 표를 쓴다 — 둘이 갈리면 "아군 진영 효과인데 적의 이동에 반응"
# 같은 상태가 생긴다.
FIELD_SCOPE_FACTIONS: dict[PassiveSkillTargetType, Optional[FactionType]] = {
    PassiveSkillTargetType.FIELD_ALLY_SIDE: FactionType.ALLY,
    PassiveSkillTargetType.FIELD_ENEMY_SIDE: FactionType.ENEMY,
    PassiveSkillTargetType.FIELD_ALL: None,
    PassiveSkillTargetType.FIELD_SUBJECT: None,
}


def field_scope_includes(
    target_type: PassiveSkillTargetType, faction: FactionType
) -> bool:
    """필드 범위가 그 진영을 포함하는지. 필드 범위가 아닌 값은 항상 False."""
    if target_type not in FIELD_SCOPE_TARGET_TYPES:
        return False
    wanted = FIELD_SCOPE_FACTIONS[target_type]
    return wanted is None or wanted == faction


@dataclass(frozen=True)
class PassiveSkillData:
    id: str
    trigger: PassiveSkillTrigger
    target_type: PassiveSkillTargetType
    effects: list[SkillEffectBase]
    description: str
    # 버프 모디파이어 경로. effects와 동시에 채워질 수 있다(상호 배타적이지 않음).
    buff_mod_event: Optional[BuffEvent] = None

    @property
    def is_field_effect(self) -> bool:
        """이 행이 캐릭터 패시브가 아니라 필드 효과인지. "스킬_패시브" 시트
        하나를 둘이 함께 쓰므로 target_type이 구분자 역할을 한다."""
        return self.target_type in FIELD_SCOPE_TARGET_TYPES

    @classmethod
    def from_dict(
        cls, data: SpreadsheetRow, passive_buff_dict: dict[str, PassiveBuffData]
    ) -> "PassiveSkillData":
        buff_mod_event: Optional[BuffEvent] = None
        top_buff_id_raw = data.get("buff_id") or None
        top_buff_id = str(top_buff_id_raw) if top_buff_id_raw is not None else None
        if top_buff_id:
            passive_buff_data = passive_buff_dict[top_buff_id]
            buff_module = importlib.import_module("battle.objects.buff.buffs")
            buff_class = getattr(buff_module, passive_buff_data.buff_class_name)
            template = buff_class._create_bare(
                id_=passive_buff_data.id,
                uid=BuffUid(
                    _TEMPLATE_CHARACTER_ID,
                    _TEMPLATE_CHARACTER_ID,
                    passive_buff_data.buff_class_name,
                ),
                given_by=_TEMPLATE_CHARACTER_ID,
                applied_to=_TEMPLATE_CHARACTER_ID,
                value=passive_buff_data.value,
                value_type=passive_buff_data.value_type,
                value_2=passive_buff_data.value_2,
                condition=passive_buff_data.condition,
                reference_buff_id=passive_buff_data.reference_buff_id,
            )
            buff_mod_event = template.create_event()

        effects: list[SkillEffectBase] = []
        for i in range(MAX_PASSIVE_EFFECT_COUNT):
            effect = parse_skill_effect(data, i)
            if effect is not None:
                effects.append(effect)

        return cls(
            id=str(data["id"]),
            trigger=PassiveSkillTrigger(data["trigger"]),
            target_type=PassiveSkillTargetType(data["target_type"]),
            effects=effects,
            buff_mod_event=buff_mod_event,
            description=str(data.get("description", "")),
        )
