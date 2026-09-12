"""대련에서 "적 후행 시" 트리거가 그 라운드의 피격에 실제로 반영되는지 검증한다.

본 전투는 이 트리거를 두 지점으로 나눠 평가한다 — 적의 지연 공격이 적용되기
전(ON_ENEMY_POST_ACTION)과 적용된 뒤(ON_ENEMY_POST_ACTION_RESOLVED). 대련은
PRE/POST 구분 없이 선공/후공을 즉시 처리하는 구조라 두 훅을 어디에 대응시킬지
직접 정해야 하는데, 둘 다 라운드 종료에 두면 앞쪽 훅이 부여하는 1턴짜리 방어
버프가 같은 end_round()의 턴 차감으로 즉시 사라져 아무 효과도 내지 못한다.
"""

import random

from battle.core.commands.parser import parse_character_command
from battle.objects.buff.models import BuffData
from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager
from helpers import get_test_preset

PASSIVE_ID = "PassiveSkill"
GUARD_BUFF_ID = "받는 대미지 감소"


def _guard_buff() -> BuffData:
    """1턴짜리 "받는 대미지 -50%" 버프. 경감이 실제로 걸렸는지 체력 숫자로
    바로 드러나도록 큰 값을 쓴다."""
    return BuffData.from_dict(
        {
            "id": GUARD_BUFF_ID,
            "buff_name": "BuffReceivedDamage",
            "duration_turn_value": 1,
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value_0": -50,
            "value_type_0": "퍼센트",
            "value_1": "",
            "value_type_1": "",
            "condition": "",
            "condition_value": "",
            "type": "버프",
            "max_stack": "",
            "reference_buff_id": "",
            "description": "",
        }
    )


def _guard_passive() -> PassiveSkillData:
    return PassiveSkillData.from_dict(
        {
            "id": PASSIVE_ID,
            "description": "",
            "trigger": "적 후행 시",
            "target_type": "자신",
            "buff_id": "",
            "effect_0": "SkillEffectAddBuff",
            "value_source_0": "",
            "value_0": "",
            "value_type_0": "",
            "buff_id_0": GUARD_BUFF_ID,
            "target_override_0": "자신",
            "condition_0": "",
            "condition_value_0": "",
        },
        passive_buff_dict={},
    )


def _run_one_round(with_passive: bool) -> int:
    """방어 패시브를 가진(또는 갖지 않은) 캐릭터가 한 대 맞고 남은 체력."""
    random.seed(20260911)
    ctx = PracticeBattlefieldContext(
        buff_dict={GUARD_BUFF_ID: _guard_buff()},
        skill_dict={},
        passive_skill_dict={PASSIVE_ID: _guard_passive()} if with_passive else {},
    )
    ctx.add_character(
        get_test_preset(
            "A", max_hp=200, passive_skill_id=PASSIVE_ID if with_passive else None
        ),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("B", atk=20), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )

    manager = PracticeRoundManager(ctx)
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    manager._first_mover, manager._second_mover = SideType.SIDE_2, SideType.SIDE_1
    manager.process_command(parse_character_command(CharacterId("B"), "[공격/A]", ctx))
    return ctx.characters[CharacterId("A")].status.curr_hp


def test_enemy_post_action_guard_buff_applies_within_the_same_round():
    assert _run_one_round(with_passive=True) > _run_one_round(with_passive=False)
