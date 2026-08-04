import importlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from battle.objects.buff.buff_events import BuffEvent
from battle.objects.buff.models import PassiveBuffData
from battle.objects.define import MAX_PASSIVE_EFFECT_COUNT
from battle.objects.models import BuffUid, CharacterId
from battle.objects.skill.models import SkillEffectBase, parse_skill_effect

# buff_mod_event 추출용 임시 인스턴스는 create_event()만 호출되고 버려지므로
# given_by/applied_to/uid는 실제로 쓰이지 않는다 — 전투 참가자가 아직 없는
# 데이터 로드 시점에 생성되기도 하고, 애초에 식별할 대상이 없다.
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
    ALL_ALLIES = "전체 아군"
    ATTACKER_OR_TARGET = "공격자 또는 대상"
    LOWEST_HP_ALLY = "체력 최저 아군"


@dataclass(frozen=True)
class PassiveSkillData:
    id: str
    trigger: PassiveSkillTrigger
    target_type: PassiveSkillTargetType
    effects: list[SkillEffectBase]
    description: str
    # 버프 모디파이어 경로. effects와 동시에 채워질 수 있다(상호 배타적이지 않음).
    buff_mod_event: Optional[BuffEvent] = None

    @classmethod
    def from_dict(
        cls, data: dict, passive_buff_dict: dict[str, PassiveBuffData]
    ) -> "PassiveSkillData":
        buff_mod_event: Optional[BuffEvent] = None
        top_buff_id = data.get("buff_id") or None
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
            id=data["id"],
            trigger=PassiveSkillTrigger(data["trigger"]),
            target_type=PassiveSkillTargetType(data["target_type"]),
            effects=effects,
            buff_mod_event=buff_mod_event,
            description=data.get("description", ""),
        )
