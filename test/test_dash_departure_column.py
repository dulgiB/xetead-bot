"""경로 광역(SkillEffectSplashAlongPath)이 출발 열을 전장 위치가 아니라 커맨드
전개 시점의 출발 위치로 보는지에 대한 테스트.

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/스킬명 대신 일반화된 이름을 쓴다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.define import (
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectDamage,
    SkillEffectMove,
    SkillEffectSplashAlongPath,
)
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

DASHER = CharacterId("돌진자")


def _context(skill: SkillData) -> BattlefieldContext:
    return BattlefieldContext(buff_dict={}, skill_dict={skill.id: skill})


def _add(
    ctx: BattlefieldContext,
    name: str,
    faction: FactionType,
    column: int,
    **kwargs,
) -> CharacterId:
    ctx.add_character(
        get_test_preset(name, **kwargs), faction, BattlefieldColumnIndex(column)
    )
    return CharacterId(name)


def _hp(ctx: BattlefieldContext, name: str) -> int:
    return ctx.characters[CharacterId(name)].status.curr_hp


def test_enemy_target_dash_keeps_its_path_splash_until_resolution():
    """기존 돌진(상대의 현재 위치 + 경로 광역)도 에너미가 선언 때 이동하고
    정산 때 경로 대미지를 재전개하므로, 출발 열을 선언 직전 위치로 봐야
    경로상 아군이 맞는다."""
    skill = SkillData(
        id="DashSkill",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectMove(
                ValueSourceType.TARGET_CURR_POSITION, None, None, None, None
            ),
            SkillEffectDamage(ValueSourceType.FIXED, 30, ValueType.INTEGER, None, None),
            SkillEffectSplashAlongPath(
                ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
            ),
        ],
        description="",
    )
    ctx = _context(skill)
    manager = RoundManager(ctx)
    _add(ctx, DASHER.name, FactionType.ENEMY, 0, skill_1_id="DashSkill")
    _add(ctx, "주대상", FactionType.ALLY, 3)
    _add(ctx, "경로", FactionType.ALLY, 1)

    manager.process_command(parse_character_command(DASHER, "[DashSkill/주대상]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert _hp(ctx, "주대상") == 70
    assert _hp(ctx, "경로") == 90


def test_target_dash_path_starts_after_an_earlier_move_in_the_same_command():
    """한 커맨드의 파트는 처리 전에 한꺼번에 전개되므로, 경로 광역이 전장
    위치를 읽으면 앞 파트의 이동 전 위치에서 경로를 잰다."""
    skill = SkillData(
        id="DashSkill",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectMove(
                ValueSourceType.TARGET_CURR_POSITION, None, None, None, None
            ),
            SkillEffectSplashAlongPath(
                ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
            ),
        ],
        description="",
    )
    ctx = _context(skill)
    manager = RoundManager(ctx)
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    _add(ctx, DASHER.name, FactionType.ALLY, 0, skill_1_id="DashSkill", attack_range=1)
    _add(ctx, "주대상", FactionType.ENEMY, 2)
    _add(ctx, "지나친 적", FactionType.ENEMY, 1)

    manager.process_command(
        parse_character_command(DASHER, "[이동/2열 - DashSkill/주대상]", ctx)
    )

    assert ctx.find_character_position(DASHER) == BattlefieldColumnIndex(2)
    assert _hp(ctx, "지나친 적") == 100
