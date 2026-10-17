"""HolderMovedThisTurnCondition을 대상별 조건으로 쓴 적 열 광역기.

적 스킬의 대미지는 적 공격 정산(POST) 때 전개되므로, 그 라운드 아군 행동에서
이동한 대상만 추가 대미지를 받는다.
"""

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
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

ENEMY = CharacterId("적군")
MOVER = CharacterId("아군_1")
STAYER = CharacterId("아군_2")


def _column_skill() -> SkillData:
    return SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleColumn",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None),
            SkillEffectDamage(
                ValueSourceType.FIXED,
                10,
                ValueType.INTEGER,
                None,
                None,
                target_condition_class_name="HolderMovedThisTurnCondition",
            ),
        ],
        description="",
    )


def _setup() -> tuple[BattlefieldContext, RoundManager]:
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"스킬_1": _column_skill()})
    ctx.add_character(
        get_test_preset(ENEMY.name, attack_range=6, skill_1_id="스킬_1"),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset(MOVER.name), FactionType.ALLY, BattlefieldColumnIndex(1)
    )
    ctx.add_character(
        get_test_preset(STAYER.name), FactionType.ALLY, BattlefieldColumnIndex(2)
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return ctx, manager


def test_only_targets_that_moved_this_round_take_the_extra_damage():
    ctx, manager = _setup()
    manager.process_command(parse_character_command(ENEMY, "[스킬_1/3열]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.process_command(parse_character_command(MOVER, "[이동/3]", ctx))

    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.characters[MOVER].status.curr_hp == 70
    assert ctx.characters[STAYER].status.curr_hp == 80
