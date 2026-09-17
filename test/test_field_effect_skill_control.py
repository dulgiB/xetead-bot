"""스킬로 필드 효과를 올리고 걷기.

expand()의 5-튜플에는 필드 효과가 들어갈 자리가 없어, 디버프 일괄 제거와
같이 expand() 옆에서 따로 불리는 훅으로 요청을 받는다. 실제 반영은 처리
시점에 하며, 에너미 커맨드가 PRE/POST 두 번 처리되므로 적용 시점을 대미지와
같은 규칙으로 맞춘다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import BattleLogEntryKind
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueType,
)
from battle.objects.field_effect.models import FieldEffectSource
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectAddFieldEffect,
    SkillEffectRemoveFieldEffect,
)
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

FIELD_EFFECT_ID = "FieldEffect"
FIELD_BUFF_ID = "FieldBuff"
ADD_SKILL_ID = "스킬_1"
REMOVE_SKILL_ID = "스킬_2"


def _field_buff() -> BuffData:
    return BuffData(
        id=FIELD_BUFF_ID,
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=10,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.BUFF,
        description="",
    )


def _field_effect() -> PassiveSkillData:
    return PassiveSkillData(
        id=FIELD_EFFECT_ID,
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=PassiveSkillTargetType.FIELD_ALLY_SIDE,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=FIELD_BUFF_ID,
                buff_add_timing=None,
            )
        ],
        description="",
    )


def _control_skill(skill_id: str, effect_class) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleSelf",
        cost=1,
        target_count=1,
        effects=[
            effect_class(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=None,
                buff_add_timing=None,
                field_effect_id=FIELD_EFFECT_ID,
            )
        ],
        description="",
    )


def _make_context() -> BattlefieldContext:
    ctx = BattlefieldContext(
        buff_dict={FIELD_BUFF_ID: _field_buff()},
        skill_dict={
            ADD_SKILL_ID: _control_skill(ADD_SKILL_ID, SkillEffectAddFieldEffect),
            REMOVE_SKILL_ID: _control_skill(
                REMOVE_SKILL_ID, SkillEffectRemoveFieldEffect
            ),
        },
        passive_skill_dict={FIELD_EFFECT_ID: _field_effect()},
    )
    ctx.add_character(
        get_test_preset("시전자", skill_1_id=ADD_SKILL_ID, skill_2_id=REMOVE_SKILL_ID),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx


def _use(ctx: BattlefieldContext, skill_id: str) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.process_command(
        parse_character_command(CharacterId("시전자"), f"[{skill_id}/시전자]", ctx)
    )
    return manager


class TestAddBySkill:
    def test_skill_puts_the_effect_on_the_field(self):
        ctx = _make_context()

        _use(ctx, ADD_SKILL_ID)

        assert FIELD_EFFECT_ID in ctx.field_effects

    def test_added_effect_then_applies_on_round_start(self):
        ctx = _make_context()
        _use(ctx, ADD_SKILL_ID)

        ctx.on_start_round()

        assert (
            ctx.buff_container.get_buff(CharacterId("시전자"), FIELD_BUFF_ID)
            is not None
        )

    def test_result_is_reported_as_a_log_entry(self):
        ctx = _make_context()
        _use(ctx, ADD_SKILL_ID)

        entries = [
            entry
            for result in ctx.results
            for entry in result.log_entries
            if entry.kind == BattleLogEntryKind.FIELD_EFFECT
        ]

        assert len(entries) == 1
        assert entries[0].target_name == FIELD_EFFECT_ID
        assert entries[0].result == "필드 효과 발생"

    def test_adding_an_already_active_effect_reports_nothing(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)

        _use(ctx, ADD_SKILL_ID)

        entries = [
            entry
            for result in ctx.results
            for entry in result.log_entries
            if entry.kind == BattleLogEntryKind.FIELD_EFFECT
        ]
        assert entries == []
        assert len(ctx.field_effects) == 1


class TestRemoveBySkill:
    def test_skill_takes_the_effect_off_the_field(self):
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.on_start_round()

        _use(ctx, REMOVE_SKILL_ID)

        assert FIELD_EFFECT_ID not in ctx.field_effects
        assert ctx.buff_container.get_buff(CharacterId("시전자"), FIELD_BUFF_ID) is None

    def test_removing_an_absent_effect_reports_nothing(self):
        ctx = _make_context()

        _use(ctx, REMOVE_SKILL_ID)

        entries = [
            entry
            for result in ctx.results
            for entry in result.log_entries
            if entry.kind == BattleLogEntryKind.FIELD_EFFECT
        ]
        assert entries == []
