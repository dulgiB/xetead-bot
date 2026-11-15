"""열 범위 광역(SkillTargetRuleColumnRange)의 사거리 판정.

지정한 중심 열만 사거리 안이면 범위로 넓어진 나머지 열의 대상은 사거리와
무관하게 맞는다. 에너미의 적 공격 정산(POST)도 같은 기준으로 다시 본다.
"""

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
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectMove
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

CASTER = CharacterId("시전자")
PUSHER = CharacterId("밀어내는 아군")
FOES = [CharacterId(f"대상 {i}") for i in range(7)]


def _area_skill() -> SkillData:
    return SkillData(
        id="광역_1",
        target_rule="SkillTargetRuleColumnRange",
        target_count=3,
        cost=0,
        effects=[
            SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
        ],
        description="",
    )


def _push_skill() -> SkillData:
    return SkillData(
        id="밀어내기",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectMove(ValueSourceType.AWAY_FROM_HOLDER, 2, None, None, None)
        ],
        description="",
    )


def _setup(
    caster_faction: FactionType, caster_column: int, attack_range: int
) -> tuple[BattlefieldContext, RoundManager]:
    skills = {s.id: s for s in (_area_skill(), _push_skill())}
    ctx = BattlefieldContext(buff_dict={}, skill_dict=skills)
    manager = RoundManager(ctx)
    phase = (
        RoundPhaseType.ENEMY_PRE_ACTION
        if caster_faction == FactionType.ENEMY
        else RoundPhaseType.ALLY_ACTION
    )
    manager.process_command(
        ChangePhaseCommand(type_=ActionType.ADMIN, target_phase=phase)
    )
    foe_faction = (
        FactionType.ALLY if caster_faction == FactionType.ENEMY else FactionType.ENEMY
    )
    ctx.add_character(
        get_test_preset(
            CASTER.name,
            skill_1_id="광역_1",
            attack_range=attack_range,
            is_enemy=caster_faction == FactionType.ENEMY,
        ),
        caster_faction,
        BattlefieldColumnIndex(caster_column),
    )
    for column, foe in enumerate(FOES):
        ctx.add_character(
            get_test_preset(foe.name, skill_1_id="밀어내기"),
            foe_faction,
            BattlefieldColumnIndex(column),
        )
    return ctx, manager


def _damaged(ctx: BattlefieldContext) -> set[CharacterId]:
    return {foe for foe in FOES if ctx.characters[foe].status.curr_hp < 100}


def test_center_in_range_hits_targets_beyond_range():
    ctx, manager = _setup(FactionType.ALLY, caster_column=3, attack_range=1)

    manager.process_command(parse_character_command(CASTER, "[광역_1/4]", ctx))

    assert _damaged(ctx) == set(FOES)


def test_center_out_of_range_is_rejected():
    ctx, manager = _setup(FactionType.ALLY, caster_column=0, attack_range=1)

    with pytest.raises(CommandValidationError):
        manager.process_command(parse_character_command(CASTER, "[광역_1/4]", ctx))


def test_enemy_area_attack_hits_all_columns_at_post():
    ctx, manager = _setup(FactionType.ENEMY, caster_column=3, attack_range=1)

    manager.process_command(parse_character_command(CASTER, "[광역_1/4]", ctx))
    for phase in (RoundPhaseType.ALLY_ACTION, RoundPhaseType.ENEMY_POST_ACTION):
        manager.process_command(
            ChangePhaseCommand(type_=ActionType.ADMIN, target_phase=phase)
        )

    assert _damaged(ctx) == set(FOES)


def test_enemy_pushed_away_from_center_misses_everyone():
    ctx, manager = _setup(FactionType.ENEMY, caster_column=3, attack_range=1)

    manager.process_command(parse_character_command(CASTER, "[광역_1/4]", ctx))
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    # 2열의 아군이 4열의 시전자를 오른쪽으로 2칸 밀어 6열로 보낸다.
    manager.process_command(
        parse_character_command(FOES[1], f"[밀어내기/{CASTER.name}]", ctx)
    )
    assert ctx.find_character_position(CASTER) == BattlefieldColumnIndex(5)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_POST_ACTION
        )
    )

    assert _damaged(ctx) == set()


def test_area_skill_without_column_is_rejected():
    """열을 빠뜨린 선언은 아무도 맞히지 못한 채 코스트만 쓰지 않도록 거부한다
    (검증 실패는 코스트 차감 전에 난다)."""
    ctx, manager = _setup(FactionType.ENEMY, caster_column=3, attack_range=1)

    with pytest.raises(CommandValidationError):
        manager.process_command(parse_character_command(CASTER, "[광역_1]", ctx))
