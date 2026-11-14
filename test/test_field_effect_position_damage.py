"""위치·이동을 보는 라운드 종료 필드 대미지.

`SkillEffectFieldDamage` + `target_condition_N`으로 만드는 세 가지 형태 —
가장자리 열에 있는 캐릭터, 이번 라운드에 이동하지 않은 캐릭터, 이번 라운드에
이동을 선언한 캐릭터 — 를 실제 라운드 진행으로 확인한다. "이동했다"와 "이동을
선언했다"를 가르는 지점(밀어내기, 자기 자신을 옮기는 돌진, admin 강제 이동)이
핵심이다.
"""

from types import SimpleNamespace
from typing import Optional

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand, ForceMoveCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
)
from battle.objects.field_effect.models import FieldEffectSource
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectFieldDamage, SkillEffectMove
from battle.objects.skill.models import SkillData
from bot.field_restore import _restore_move_records
from helpers import get_test_preset

EFFECT_ID = "FieldEffect"
DAMAGE = 15


def _round_end_damage(condition: str, value: Optional[int] = None) -> PassiveSkillData:
    return PassiveSkillData(
        id=EFFECT_ID,
        trigger=PassiveSkillTrigger.ROUND_END,
        target_type=PassiveSkillTargetType.FIELD_ALL,
        effects=[
            SkillEffectFieldDamage(
                value_source=None,
                value=DAMAGE,
                value_type=None,
                buff_id=None,
                buff_add_timing=None,
                target_condition_class_name=condition,
                target_condition_value=value,
            )
        ],
        description="",
    )


_PUSH = SkillData(
    id="밀어내기",
    target_rule="SkillTargetRuleNamed",
    target_count=1,
    cost=0,
    effects=[SkillEffectMove(ValueSourceType.AWAY_FROM_HOLDER, 1, None, None, None)],
    description="",
)
_DASH = SkillData(
    id="돌진",
    target_rule="SkillTargetRuleNamed",
    target_count=1,
    cost=0,
    effects=[
        SkillEffectMove(ValueSourceType.TARGET_CURR_POSITION, None, None, None, None)
    ],
    description="",
)


def _setup(
    effect: PassiveSkillData,
) -> tuple[BattlefieldContext, RoundManager]:
    ctx = BattlefieldContext(
        buff_dict={},
        skill_dict={_PUSH.id: _PUSH, _DASH.id: _DASH},
        passive_skill_dict={effect.id: effect},
    )
    ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    return ctx, manager


def _add(ctx: BattlefieldContext, name: str, faction: FactionType, column: int, **kw):
    ctx.add_character(
        get_test_preset(name, skill_1_id="밀어내기", skill_2_id="돌진", **kw),
        faction,
        BattlefieldColumnIndex(column),
    )


def _run(manager: RoundManager, ctx: BattlefieldContext, user: str, command: str):
    manager.process_command(parse_character_command(CharacterId(user), command, ctx))


def _end_round(manager: RoundManager) -> None:
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)


def _hp(ctx: BattlefieldContext, name: str) -> int:
    return ctx.characters[CharacterId(name)].status.curr_hp


class TestEdgeColumns:
    def test_only_columns_1_2_6_7_take_damage(self):
        ctx, manager = _setup(_round_end_damage("HolderInEdgeColumnsCondition", 2))
        for column in range(7):
            _add(ctx, f"아군{column + 1}", FactionType.ALLY, column)
        _add(ctx, "적군", FactionType.ENEMY, 6)

        _end_round(manager)

        assert [_hp(ctx, f"아군{c}") for c in range(1, 8)] == [
            85,
            85,
            100,
            100,
            100,
            85,
            85,
        ]
        assert _hp(ctx, "적군") == 85

    def test_position_at_round_end_counts(self):
        ctx, manager = _setup(_round_end_damage("HolderInEdgeColumnsCondition", 2))
        _add(ctx, "이동자", FactionType.ALLY, 0)

        _run(manager, ctx, "이동자", "[이동/3]")
        _end_round(manager)

        assert _hp(ctx, "이동자") == 100

    def test_multi_column_enemy_counts_any_occupied_column(self):
        ctx, manager = _setup(_round_end_damage("HolderInEdgeColumnsCondition", 2))
        _add(ctx, "덩치", FactionType.ENEMY, 1, span=2)
        _add(ctx, "가운데", FactionType.ENEMY, 2, span=3)

        _end_round(manager)

        assert _hp(ctx, "덩치") == 85
        assert _hp(ctx, "가운데") == 100


class TestDidNotMove:
    def test_staying_still_takes_damage(self):
        ctx, manager = _setup(_round_end_damage("HolderDidNotMoveThisTurnCondition"))
        _add(ctx, "이동자", FactionType.ALLY, 0)
        _add(ctx, "가만히", FactionType.ALLY, 0)

        _run(manager, ctx, "이동자", "[이동/2]")
        _end_round(manager)

        assert _hp(ctx, "이동자") == 100
        assert _hp(ctx, "가만히") == 85

    def test_being_pushed_counts_as_moving(self):
        ctx, manager = _setup(_round_end_damage("HolderDidNotMoveThisTurnCondition"))
        _add(ctx, "아군", FactionType.ALLY, 0)
        _add(ctx, "적군", FactionType.ENEMY, 2)

        _run(manager, ctx, "아군", "[밀어내기/적군]")
        _end_round(manager)

        assert _hp(ctx, "아군") == 85
        assert _hp(ctx, "적군") == 100

    def test_move_record_resets_each_round(self):
        ctx, manager = _setup(_round_end_damage("HolderDidNotMoveThisTurnCondition"))
        _add(ctx, "이동자", FactionType.ALLY, 0)

        _run(manager, ctx, "이동자", "[이동/2]")
        _end_round(manager)
        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        _end_round(manager)

        assert _hp(ctx, "이동자") == 85


class TestDeclaredMove:
    def test_move_command_takes_damage(self):
        ctx, manager = _setup(_round_end_damage("HolderDeclaredMoveThisTurnCondition"))
        _add(ctx, "이동자", FactionType.ALLY, 0)
        _add(ctx, "가만히", FactionType.ALLY, 0)

        _run(manager, ctx, "이동자", "[이동/2]")
        _end_round(manager)

        assert _hp(ctx, "이동자") == 85
        assert _hp(ctx, "가만히") == 100

    def test_being_pushed_is_not_declaring(self):
        ctx, manager = _setup(_round_end_damage("HolderDeclaredMoveThisTurnCondition"))
        _add(ctx, "아군", FactionType.ALLY, 0)
        _add(ctx, "적군", FactionType.ENEMY, 2)

        _run(manager, ctx, "아군", "[밀어내기/적군]")
        _end_round(manager)

        assert _hp(ctx, "아군") == 100
        assert _hp(ctx, "적군") == 100

    def test_dashing_skill_counts_as_declaring(self):
        ctx, manager = _setup(_round_end_damage("HolderDeclaredMoveThisTurnCondition"))
        _add(ctx, "아군", FactionType.ALLY, 0)
        _add(ctx, "적군", FactionType.ENEMY, 2)

        _run(manager, ctx, "아군", "[돌진/적군]")
        _end_round(manager)

        assert ctx.find_character_position(CharacterId("아군")) == (
            BattlefieldColumnIndex(2)
        )
        assert _hp(ctx, "아군") == 85
        assert _hp(ctx, "적군") == 100

    def test_admin_force_move_is_not_declaring(self):
        ctx, manager = _setup(_round_end_damage("HolderDeclaredMoveThisTurnCondition"))
        _add(ctx, "아군", FactionType.ALLY, 0)

        manager.process_command(
            ForceMoveCommand(
                type_=ActionType.ADMIN,
                targets=[CharacterId("아군")],
                to_position=BattlefieldColumnIndex(2),
            )
        )
        _end_round(manager)

        assert _hp(ctx, "아군") == 100

    def test_enemy_move_declared_in_pre_action_counts(self):
        ctx, manager = _setup(_round_end_damage("HolderDeclaredMoveThisTurnCondition"))
        _add(ctx, "적군", FactionType.ENEMY, 0)
        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)

        _run(manager, ctx, "적군", "[이동/2]")
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        _end_round(manager)

        assert _hp(ctx, "적군") == 85


class TestMoveRecordRestore:
    """라운드 도중 재기동해도 라운드 종료 판정이 같은 기록을 읽어야 한다."""

    def test_restores_both_records(self):
        ctx, manager = _setup(_round_end_damage("HolderDeclaredMoveThisTurnCondition"))
        _add(ctx, "이동자", FactionType.ALLY, 0)
        _add(ctx, "밀림", FactionType.ALLY, 1)
        row = SimpleNamespace(
            meta={
                "moved_this_round": ["이동자", "밀림"],
                "move_declared_this_round": ["이동자"],
            }
        )

        _restore_move_records(ctx, row)  # type: ignore[arg-type]
        _end_round(manager)

        assert ctx.moved_this_round == {CharacterId("이동자"), CharacterId("밀림")}
        assert _hp(ctx, "이동자") == 85
        assert _hp(ctx, "밀림") == 100

    def test_missing_keys_mean_nobody_moved(self):
        ctx, _ = _setup(_round_end_damage("HolderDeclaredMoveThisTurnCondition"))
        ctx.moved_this_round = {CharacterId("x")}

        _restore_move_records(ctx, SimpleNamespace(meta={}))  # type: ignore[arg-type]

        assert ctx.moved_this_round == set()
        assert ctx.move_declared_this_round == set()
