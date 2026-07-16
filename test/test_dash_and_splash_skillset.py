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
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
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
            SkillEffectMove(ValueSourceType.TARGET_CURR_POSITION, None, None, None, None),
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

    cmd = parse_character_command(ally_id, "[스킬/Cost3Skill/적군 주대상]")
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

    cmd = parse_character_command(ally_id, "[스킬/Cost3Skill/적군 주대상]")
    manager.process_command(cmd)

    assert ctx.characters[main_target_id].status.curr_hp < 100
    assert ctx.characters[path_ally_id].status.curr_hp < 100
    assert ctx.characters[same_col_ally_id].status.curr_hp < 100
    assert ctx.characters[outside_id].status.curr_hp == 100

    # 주대상(320%)이 경로상 다른 적(40%)보다 더 큰 대미지를 받아야 한다.
    main_damage = 100 - ctx.characters[main_target_id].status.curr_hp
    path_damage = 100 - ctx.characters[path_ally_id].status.curr_hp
    assert main_damage > path_damage
