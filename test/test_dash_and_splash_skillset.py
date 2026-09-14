"""
돌진 + 경로 광역 스킬(코스트 3) 관련 테스트.

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/스킬명 대신 일반화된 이름을 쓴다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectMove
from battle.objects.skill.effects.effect_splash_along_path import (
    SkillEffectSplashAlongPath,
)
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


@pytest.fixture
def cost3_skill() -> SkillData:
    """사거리 내 대상 1명의 위치로 돌진해 320% 대미지, 경로상 다른 적 전체에게
    40% 대미지(주대상 제외)."""
    return SkillData(
        id="Cost3Skill",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=3,
        effects=[
            SkillEffectMove(
                ValueSourceType.TARGET_CURR_POSITION, None, None, None, None
            ),
            SkillEffectDamage(
                ValueSourceType.STAT_ATK_ROLL, 320, ValueType.PERCENT, None, None
            ),
            SkillEffectSplashAlongPath(
                ValueSourceType.STAT_ATK_ROLL, 40, ValueType.PERCENT, None, None
            ),
        ],
        description="",
    )


@pytest.fixture
def battle(cost3_skill) -> tuple[BattlefieldContext, RoundManager]:
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"Cost3Skill": cost3_skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return ctx, manager


def test_caster_dashes_to_target_position(battle):
    """스킬 사용 시 시전자가 주대상의 위치로 이동해야 한다."""
    ctx, manager = battle
    ally_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="Cost3Skill", attack_range=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 주대상"), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )

    cmd = parse_character_command(ally_id, "[Cost3Skill/적군 주대상]", ctx)
    manager.process_command(cmd)

    assert ctx.find_character_position(ally_id) == BattlefieldColumnIndex(3)


def test_main_target_and_path_enemies_take_damage_excluding_bystanders(battle):
    """주대상은 320%, 경로(시전자 원래 위치~대상 위치) 위의 다른 적은 40% 대미지를
    받아야 하고, 경로 밖의 적은 영향이 없어야 한다."""
    ctx, manager = battle
    ally_id = CharacterId("아군 1")
    main_target_id = CharacterId("적군 주대상")
    path_ally_id = CharacterId("적군 경로상")
    same_col_ally_id = CharacterId("적군 같은열")
    outside_id = CharacterId("적군 범위밖")

    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="Cost3Skill", attack_range=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    # 시전자 원래 위치(0) ~ 주대상 위치(3) 사이 = COL1~COL4
    ctx.add_character(
        get_test_preset("적군 주대상"), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )
    ctx.add_character(
        get_test_preset("적군 경로상"), FactionType.ENEMY, BattlefieldColumnIndex(1)
    )
    # 주대상과 같은 열(COL4)의 다른 적 — 경로 끝 열이므로 광역에 포함되어야 함
    ctx.add_character(
        get_test_preset("적군 같은열"), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )
    # 경로 밖(COL5)
    ctx.add_character(
        get_test_preset("적군 범위밖"), FactionType.ENEMY, BattlefieldColumnIndex(4)
    )

    cmd = parse_character_command(ally_id, "[Cost3Skill/적군 주대상]", ctx)
    manager.process_command(cmd)

    assert ctx.characters[main_target_id].status.curr_hp < 100
    assert ctx.characters[path_ally_id].status.curr_hp < 100
    assert ctx.characters[same_col_ally_id].status.curr_hp < 100
    assert ctx.characters[outside_id].status.curr_hp == 100

    # 주대상(320%)이 경로상 다른 적(40%)보다 더 큰 대미지를 받아야 한다.
    main_damage = 100 - ctx.characters[main_target_id].status.curr_hp
    path_damage = 100 - ctx.characters[path_ally_id].status.curr_hp
    assert main_damage > path_damage


def _given_damage_buff(buff_id: str, percent: int) -> BuffData:
    return BuffData(
        id=buff_id,
        description="",
        buff_class_name="BuffGivenDamage",
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=percent,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.BUFF,
    )


def test_path_splash_also_receives_the_casters_given_damage_buff(cost3_skill):
    """ON_ATTACK 디스패치는 커맨드당 공격자 1회지만, 주는 대미지 배율은
    effect마다 다시 얹혀야 한다 — 그러지 않으면 두 번째 이후 effect인 경로
    광역만 시전자의 버프/디버프를 통째로 빠뜨린다.

    milestone_n=0 + atk 고정으로 굴림을 없애 수치를 직접 비교한다.
    """
    ctx = BattlefieldContext(
        buff_dict={"강화": _given_damage_buff("강화", 50)},
        skill_dict={"Cost3Skill": cost3_skill},
        milestone_n=0,
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    caster_id = CharacterId("아군 1")
    main_target_id = CharacterId("적군 주대상")
    path_target_id = CharacterId("적군 경로상")
    ctx.add_character(
        get_test_preset("아군 1", atk=100, skill_1_id="Cost3Skill", attack_range=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 주대상", max_hp=10000),
        FactionType.ENEMY,
        BattlefieldColumnIndex(3),
    )
    ctx.add_character(
        get_test_preset("적군 경로상", max_hp=10000),
        FactionType.ENEMY,
        BattlefieldColumnIndex(1),
    )
    ctx.buff_container.add(
        BuffAddData(given_by=caster_id, applied_to=caster_id, buff_id="강화")
    )

    manager.process_command(
        parse_character_command(caster_id, "[Cost3Skill/적군 주대상]", ctx)
    )

    main_damage = 10000 - ctx.characters[main_target_id].status.curr_hp
    path_damage = 10000 - ctx.characters[path_target_id].status.curr_hp
    assert main_damage == 480  # 100 × 3.2 × 1.5
    assert path_damage == 60  # 100 × 0.4 × 1.5


def test_given_damage_buff_is_not_applied_twice_to_a_multi_target_splash(cost3_skill):
    """수치 수정자 이벤트는 그 effect의 대미지 항목 전체를 훑으므로, 광역
    대상 수만큼 재적용하면 배율이 중복으로 쌓인다. (effect, 보유자)당 1회로
    막혀 있는지 확인한다."""
    ctx = BattlefieldContext(
        buff_dict={"강화": _given_damage_buff("강화", 50)},
        skill_dict={"Cost3Skill": cost3_skill},
        milestone_n=0,
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", atk=100, skill_1_id="Cost3Skill", attack_range=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 주대상", max_hp=10000),
        FactionType.ENEMY,
        BattlefieldColumnIndex(3),
    )
    for name, column in (("적군 경로 1", 1), ("적군 경로 2", 1), ("적군 경로 3", 2)):
        ctx.add_character(
            get_test_preset(name, max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(column),
        )
    ctx.buff_container.add(
        BuffAddData(given_by=caster_id, applied_to=caster_id, buff_id="강화")
    )

    manager.process_command(
        parse_character_command(caster_id, "[Cost3Skill/적군 주대상]", ctx)
    )

    for name in ("적군 경로 1", "적군 경로 2", "적군 경로 3"):
        damage = 10000 - ctx.characters[CharacterId(name)].status.curr_hp
        assert damage == 60  # 100 × 0.4 × 1.5 — 1.5가 한 번만 곱해져야 한다
