"""적군 POST 정산 시점의 사거리 재검증.

적군 공격은 PRE에서 선언·검증되고 POST에서 적용되므로, 그 사이 아군 행동으로
대상이 사거리 밖으로 나가면 공격이 빗나가야 한다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import BattleLogEntryKind
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectDamage,
    SkillEffectMove,
)
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

PUSHER = CharacterId("아군 1")
TARGET = CharacterId("아군 2")
ENEMY = CharacterId("적군 1")


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


def _strike_with_debuff_skill() -> SkillData:
    return SkillData(
        id="표식타",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(
                ValueSourceType.STAT_ATK, 100, ValueType.INTEGER, None, None
            ),
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id="표식",
                buff_add_timing=None,
            ),
        ],
        description="",
    )


def _mark_buff() -> BuffData:
    return BuffData(
        id="표식",
        buff_class_name="BuffReceivedDamage",
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=10,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.DEBUFF,
        description="",
    )


def _setup(enemy_range: int) -> tuple[BattlefieldContext, RoundManager]:
    ctx = BattlefieldContext(
        buff_dict={"표식": _mark_buff()},
        skill_dict={"밀어내기": _push_skill(), "표식타": _strike_with_debuff_skill()},
    )
    manager = RoundManager(ctx)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="밀어내기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(1)
    )
    ctx.add_character(
        get_test_preset(
            "적군 1", atk=30, attack_range=enemy_range, skill_1_id="표식타"
        ),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    return ctx, manager


def _declare_push_and_resolve(
    ctx: BattlefieldContext, manager: RoundManager, enemy_command: str
) -> None:
    manager.process_command(parse_character_command(ENEMY, enemy_command, ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    # 1열 → 3열(인덱스 1 → 3): 0열 적의 사거리 1 밖으로 밀려난다.
    manager.process_command(parse_character_command(PUSHER, "[밀어내기/아군 2]", ctx))
    assert ctx.find_character_position(TARGET) == BattlefieldColumnIndex(3)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)


def test_attack_misses_target_pushed_out_of_range():
    ctx, manager = _setup(enemy_range=1)
    _declare_push_and_resolve(ctx, manager, "[공격/아군 2]")

    assert ctx.characters[TARGET].status.curr_hp == 100
    entries = [
        entry
        for result in manager.get_last_post_action_results()[ENEMY]
        for entry in result.log_entries
    ]
    assert [(e.target_name, e.kind) for e in entries] == [
        (TARGET.name, BattleLogEntryKind.NO_EFFECT)
    ]


def test_debuff_of_missed_attack_is_not_applied():
    ctx, manager = _setup(enemy_range=1)
    _declare_push_and_resolve(ctx, manager, "[표식타/아군 2]")

    assert ctx.characters[TARGET].status.curr_hp == 100
    assert ctx.buff_container.get_buff(TARGET, "표식") is None


def test_attack_still_hits_target_moved_within_range():
    ctx, manager = _setup(enemy_range=3)
    _declare_push_and_resolve(ctx, manager, "[공격/아군 2]")

    assert ctx.characters[TARGET].status.curr_hp < 100
