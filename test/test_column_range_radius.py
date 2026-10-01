"""SkillTargetRuleColumnRange는 시트의 target_count를 입력 대상 수가 아니라
지정한 열 양옆으로 넓힐 열 수로 읽는다(1 → 3열, 2 → 5열)."""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
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

_CASTER = CharacterId("아군 1")
# 4열(index 3)을 중심으로 2~6열에 한 명씩 둔다.
_ENEMY_COLUMNS = {f"적군 {i}": i for i in range(1, 6)}


def _setup(target_count: int) -> tuple[BattlefieldContext, RoundManager]:
    skill = SkillData(
        id="스킬_1",
        target_rule="SkillTargetRuleColumnRange",
        target_count=target_count,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    ctx = BattlefieldContext(buff_dict={}, skill_dict={skill.id: skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    ctx.add_character(
        get_test_preset(_CASTER.name, skill_1_id=skill.id, attack_range=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(3),
    )
    for name, column in _ENEMY_COLUMNS.items():
        ctx.add_character(
            get_test_preset(name), FactionType.ENEMY, BattlefieldColumnIndex(column)
        )
    return ctx, manager


def _damaged(ctx: BattlefieldContext) -> set[str]:
    return {
        name
        for name in _ENEMY_COLUMNS
        if ctx.characters[CharacterId(name)].status.curr_hp < 100
    }


@pytest.mark.parametrize(
    ("target_count", "expected"),
    [
        (1, {"적군 2", "적군 3", "적군 4"}),
        (2, {"적군 1", "적군 2", "적군 3", "적군 4", "적군 5"}),
    ],
)
def test_target_count_sets_radius(target_count, expected):
    ctx, manager = _setup(target_count)

    manager.process_command(parse_character_command(_CASTER, "[스킬_1/4]", ctx))

    assert _damaged(ctx) == expected


def test_accepts_only_one_column_even_with_larger_target_count():
    ctx, manager = _setup(target_count=2)

    with pytest.raises(CommandValidationError):
        manager.process_command(parse_character_command(_CASTER, "[스킬_1/3/5]", ctx))
