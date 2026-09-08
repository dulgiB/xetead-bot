"""열 지정 스킬과 개체 지정 스킬에 서로 반대되는 대상을 입력했을 때,
AssertionError로 터지는 대신 CommandValidationError로 안내되는지 검증한다.

AssertionError는 커맨드 처리 최상위(`main.py`의 `_process_notification`)에서
"멘션 처리 중 오류"로만 잡혀 서버 로그에 남고, 입력자에게는 아무 답글도
가지 않는다 — 입력 실수를 한 admin/플레이어 입장에서는 봇이 통째로 멈춘
것처럼 보인다."""

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


def _damage_skill(skill_id: str, target_rule: str) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule=target_rule,
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="",
    )


def _setup(skill: SkillData) -> tuple[BattlefieldContext, RoundManager, CharacterId]:
    ctx = BattlefieldContext(buff_dict={}, skill_dict={skill.id: skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    caster_id = CharacterId("아군 1")
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id=skill.id, attack_range=3),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx, manager, caster_id


def _run(ctx, manager, caster_id, text):
    manager.process_command(parse_character_command(caster_id, text, ctx))


@pytest.mark.parametrize(
    "target_rule",
    [
        "SkillTargetRuleColumn",
        "SkillTargetRuleColumnRange",
        "SkillTargetRuleAllyColumn",
    ],
)
def test_column_skill_given_character_name_reports_validation_error(target_rule):
    """열 광역 스킬에 캐릭터 이름을 넣는 입력 실수는 흔하다 — 조용히
    터지지 않고 "열을 지정하라"는 안내가 나가야 한다."""
    skill = _damage_skill("스킬_1", target_rule)
    ctx, manager, caster_id = _setup(skill)

    with pytest.raises(CommandValidationError) as e:
        _run(ctx, manager, caster_id, "[스킬_1/적군 1]")

    assert "열" in str(e.value)


def test_named_skill_given_column_reports_validation_error():
    """반대 방향의 입력 실수(개체 지정 스킬에 열 번호)도 마찬가지다."""
    skill = _damage_skill("스킬_1", "SkillTargetRuleNamed")
    ctx, manager, caster_id = _setup(skill)

    with pytest.raises(CommandValidationError) as e:
        _run(ctx, manager, caster_id, "[스킬_1/1열]")

    assert "캐릭터" in str(e.value)


def test_column_skill_with_correct_column_target_still_works():
    """안내 문구를 추가하면서 정상 입력까지 막지 않았는지 확인한다."""
    skill = _damage_skill("스킬_1", "SkillTargetRuleColumn")
    ctx, manager, caster_id = _setup(skill)

    _run(ctx, manager, caster_id, "[스킬_1/1열]")

    assert ctx.characters[CharacterId("적군 1")].status.curr_hp == 95
