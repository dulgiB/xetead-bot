"""필드 효과 코어: 등록/해제, 필드 범위 대상 해석, 중간 참전 반영.

필드 효과는 캐릭터가 아니라 전장에 붙으므로 홀더가 될 캐릭터가 없다. 그래서
"홀더를 보지 않고 진영으로 대상을 잡는가", "걷을 때 자기가 부여한 버프만
회수하는가"가 이 계층의 핵심이다.
"""

import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
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
from battle.objects.skill.effects import SkillEffectAddBuff
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import SideType
from helpers import get_test_preset

FIELD_BUFF_ID = "FieldBuff"
FIELD_EFFECT_ID = "FieldEffect"
CHARACTER_PASSIVE_ID = "PassiveSkill"


def _make_field_buff() -> BuffData:
    """필드 효과가 뿌리는 버프. 지속 턴수를 비워 둬(패시브) 라운드 종료
    차감으로 사라지지 않게 한다 — 필드 효과 자체가 명시적 해제 전까지
    유지되므로 그것이 뿌리는 버프도 같은 수명을 가져야 한다."""
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


def _make_field_effect(
    target_type: PassiveSkillTargetType = PassiveSkillTargetType.FIELD_ALLY_SIDE,
    trigger: PassiveSkillTrigger = PassiveSkillTrigger.ROUND_START,
) -> PassiveSkillData:
    return PassiveSkillData(
        id=FIELD_EFFECT_ID,
        trigger=trigger,
        target_type=target_type,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=FIELD_BUFF_ID,
                buff_add_timing=None,
            )
        ],
        description="전장 효과",
    )


def _make_character_passive() -> PassiveSkillData:
    """필드 범위가 아닌 평범한 캐릭터 패시브 — 필드 효과로 올리면 거부돼야 한다."""
    return PassiveSkillData(
        id=CHARACTER_PASSIVE_ID,
        trigger=PassiveSkillTrigger.ROUND_START,
        target_type=PassiveSkillTargetType.SELF,
        effects=[],
        description="",
    )


def _make_context(
    target_type: PassiveSkillTargetType = PassiveSkillTargetType.FIELD_ALLY_SIDE,
    trigger: PassiveSkillTrigger = PassiveSkillTrigger.ROUND_START,
) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={FIELD_BUFF_ID: _make_field_buff()},
        skill_dict={},
        passive_skill_dict={
            FIELD_EFFECT_ID: _make_field_effect(target_type, trigger),
            CHARACTER_PASSIVE_ID: _make_character_passive(),
        },
    )


def _add_characters(ctx: BattlefieldContext) -> None:
    ctx.add_character(
        get_test_preset("아군_1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군_2"), FactionType.ALLY, BattlefieldColumnIndex(2)
    )
    ctx.add_character(
        get_test_preset("적군_1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )


def _start_round(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    ctx.on_start_round()
    return manager


def _has_field_buff(ctx: BattlefieldContext, name: str) -> bool:
    return ctx.buff_container.get_buff(CharacterId(name), FIELD_BUFF_ID) is not None


class TestRegistration:
    def test_adds_effect_and_reports_it(self):
        ctx = _make_context()
        effect = ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)

        assert effect is not None
        assert effect.id == FIELD_EFFECT_ID
        assert FIELD_EFFECT_ID in ctx.field_effects
        assert [e.id for e in ctx.field_effects.as_list()] == [FIELD_EFFECT_ID]

    def test_duplicate_add_is_ignored(self):
        """지속 턴수가 없어 갱신할 것이 없으므로 재부여는 무시된다."""
        ctx = _make_context()
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)

        assert ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.SKILL) is None
        assert len(ctx.field_effects) == 1

    def test_unknown_id_is_rejected(self):
        ctx = _make_context()
        with pytest.raises(CommandValidationError):
            ctx.add_field_effect("없는효과", FieldEffectSource.ADMIN)

    def test_character_passive_is_rejected(self):
        """필드 범위가 아닌 패시브를 올리면 대상이 하나도 안 잡혀 조용히
        아무 일도 안 일어난다 — 그러니 등록 시점에 거부해야 한다."""
        ctx = _make_context()
        with pytest.raises(CommandValidationError):
            ctx.add_field_effect(CHARACTER_PASSIVE_ID, FieldEffectSource.ADMIN)

    def test_removing_absent_effect_returns_none(self):
        ctx = _make_context()
        assert ctx.remove_field_effect(FIELD_EFFECT_ID) is None


class TestFieldScopeTargeting:
    def test_ally_side_buffs_only_allies(self):
        ctx = _make_context(PassiveSkillTargetType.FIELD_ALLY_SIDE)
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        _start_round(ctx)

        assert _has_field_buff(ctx, "아군_1")
        assert _has_field_buff(ctx, "아군_2")
        assert not _has_field_buff(ctx, "적군_1")

    def test_enemy_side_buffs_only_enemies(self):
        ctx = _make_context(PassiveSkillTargetType.FIELD_ENEMY_SIDE)
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        _start_round(ctx)

        assert not _has_field_buff(ctx, "아군_1")
        assert _has_field_buff(ctx, "적군_1")

    def test_field_all_buffs_both_sides(self):
        ctx = _make_context(PassiveSkillTargetType.FIELD_ALL)
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        _start_round(ctx)

        assert _has_field_buff(ctx, "아군_1")
        assert _has_field_buff(ctx, "아군_2")
        assert _has_field_buff(ctx, "적군_1")

    def test_battle_start_trigger_fires_on_battle_start(self):
        ctx = _make_context(trigger=PassiveSkillTrigger.BATTLE_START)
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.on_battle_start()

        assert _has_field_buff(ctx, "아군_1")


class TestRemoval:
    def test_remove_revokes_granted_buffs(self):
        ctx = _make_context()
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        _start_round(ctx)
        assert _has_field_buff(ctx, "아군_1")

        removed = ctx.remove_field_effect(FIELD_EFFECT_ID)

        assert removed is not None
        assert FIELD_EFFECT_ID not in ctx.field_effects
        assert not _has_field_buff(ctx, "아군_1")
        assert not _has_field_buff(ctx, "아군_2")

    def test_remove_does_not_revoke_other_effects_buffs(self):
        """홀더 센티넬이 효과마다 고유하므로, 한 효과를 걷어도 다른 효과가
        부여한 같은 버프는 남아야 한다."""
        other_id = "FieldEffect2"
        ctx = _make_context()
        ctx._passive_skill_dictionary[other_id] = PassiveSkillData(
            id=other_id,
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
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.add_field_effect(other_id, FieldEffectSource.ADMIN)
        _start_round(ctx)

        ctx.remove_field_effect(FIELD_EFFECT_ID)

        assert _has_field_buff(ctx, "아군_1")

    def test_removed_effect_stops_reapplying(self):
        ctx = _make_context()
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        _start_round(ctx)
        ctx.remove_field_effect(FIELD_EFFECT_ID)

        ctx.on_start_round()

        assert not _has_field_buff(ctx, "아군_1")


class TestMidBattleJoin:
    def test_newcomer_receives_standing_effect_immediately(self):
        """라운드 시작을 기다리지 않고 참전 즉시 받아야 한다."""
        ctx = _make_context()
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        _start_round(ctx)

        ctx.add_character(
            get_test_preset("증원"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )

        assert _has_field_buff(ctx, "증원")

    def test_newcomer_on_other_side_is_not_affected(self):
        ctx = _make_context(PassiveSkillTargetType.FIELD_ALLY_SIDE)
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)
        _start_round(ctx)

        ctx.add_character(
            get_test_preset("증원적"), FactionType.ENEMY, BattlefieldColumnIndex(1)
        )

        assert not _has_field_buff(ctx, "증원적")

    def test_reactive_trigger_does_not_fire_on_join(self):
        """반응형 트리거는 그 사건이 일어날 때 발동하는 것이지, 참전했다고
        발동할 일이 아니다."""
        ctx = _make_context(trigger=PassiveSkillTrigger.ON_ENEMY_MOVE)
        _add_characters(ctx)
        ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN)

        ctx.add_character(
            get_test_preset("증원"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )

        assert not _has_field_buff(ctx, "증원")


class TestPracticeModesExcluded:
    def test_practice_context_refuses_field_effects(self):
        ctx = PracticeBattlefieldContext(
            buff_dict={FIELD_BUFF_ID: _make_field_buff()},
            skill_dict={},
            passive_skill_dict={FIELD_EFFECT_ID: _make_field_effect()},
        )
        ctx.add_character(
            get_test_preset("대련_1"), SideType.SIDE_1, BattlefieldColumnIndex(0)
        )

        assert ctx.add_field_effect(FIELD_EFFECT_ID, FieldEffectSource.ADMIN) is None
        assert len(ctx.field_effects) == 0
