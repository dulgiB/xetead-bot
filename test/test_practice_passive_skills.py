"""
PracticeBattlefieldContext가 passive_skill_dict를 실제로 전달받아 패시브
스킬을 등록하는지 검증한다.

이전에는 PracticeBattlefieldContext.__init__이 passive_skill_dict 파라미터
자체를 받지 않아(app/bot/commands/admin.py의 두 대련/상시전투 시작 지점
모두 load_battle_data()가 반환한 값을 `_passive_skill_dict`로 버리고
있었음), 대련/상시전투에서는 어떤 캐릭터의 패시브 스킬도 전혀 발동하지
않았다.
"""

from battle.core.commands.parser import parse_character_command
from battle.objects.buff.buffs import BuffGivenDamage
from battle.objects.define import BattlefieldColumnIndex, ValueType
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager
from helpers import get_test_preset

PASSIVE_ID = "PassiveSkill"


def _make_buff_mod_event(value: int):
    """PassiveSkillData.from_dict()가 '버프_패시브' 시트 행을 buff_mod_event로
    변환하는 방식을 그대로 재현."""
    temp = object.__new__(BuffGivenDamage)
    temp.id = "PassiveBuff"
    temp.value = value
    temp.value_type = ValueType.PERCENT
    temp.condition = None
    return temp.create_event()


def _make_context() -> PracticeBattlefieldContext:
    passive = PassiveSkillData(
        id=PASSIVE_ID,
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[],
        description="",
        buff_mod_event=_make_buff_mod_event(-30),
    )
    return PracticeBattlefieldContext(
        buff_dict={}, skill_dict={}, passive_skill_dict={PASSIVE_ID: passive}
    )


def _attack_and_measure_damage(
    manager: PracticeRoundManager,
    ctx: PracticeBattlefieldContext,
    attacker_id: CharacterId,
    target_id: CharacterId,
) -> int:
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    if manager.first_mover != ctx.get_side(attacker_id):
        manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
    hp_before = ctx.characters[target_id].status.curr_hp
    cmd = parse_character_command(attacker_id, "[공격/대상]", ctx)
    manager.process_command(cmd)
    return hp_before - ctx.characters[target_id].status.curr_hp


def test_passive_skill_dict_is_wired_through_and_applies():
    """대련 컨텍스트에 등록된 패시브(주는 대미지 -30%)가 실제로 적용돼야 한다."""
    ctx = _make_context()
    manager = PracticeRoundManager(ctx)
    attacker_id = CharacterId("공격수")
    target_id = CharacterId("대상")

    # ATK를 키워 -30%(×0.7) 배율이 1d6 변동을 항상 압도하도록 한다.
    # 무버프딜: ATK+1d6 = 31~36. -30%: floor(31*0.7)=21 ~ floor(36*0.7)=25.
    ctx.add_character(
        get_test_preset("공격수", atk=30, passive_skill_id=PASSIVE_ID, max_hp=1000),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("대상", max_hp=1000),
        SideType.SIDE_2,
        BattlefieldColumnIndex(0),
    )

    damage = _attack_and_measure_damage(manager, ctx, attacker_id, target_id)

    assert damage < 31


def test_passive_skill_dict_defaults_to_empty_without_crashing():
    """passive_skill_dict를 생략해도(기존 호출부 호환) 에러 없이 동작해야 한다."""
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    manager = PracticeRoundManager(ctx)
    attacker_id = CharacterId("공격수")
    target_id = CharacterId("대상")

    ctx.add_character(
        get_test_preset("공격수", atk=5), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("대상", max_hp=1000), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )

    damage = _attack_and_measure_damage(manager, ctx, attacker_id, target_id)

    assert damage > 0
