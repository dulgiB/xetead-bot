"""필드 효과의 반응형 트리거(기믹 2): 특정 행동 시 버프/디버프 부여.

반응형 훅 4종은 모두 BuffContainer._collect_reactive_event_pairs()를 지나며,
그 판정은 홀더가 전장에 있어야 통과한다. 필드 효과에는 홀더가 없으므로
"사건 당사자의 진영이 효과의 필드 범위에 드는가"로 대신 가린다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
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
from battle.objects.skill.effects import SkillEffectAddBuff
from helpers import get_test_preset

MARK_BUFF_ID = "MarkBuff"
EFFECT_ID = "FieldEffect"


def _mark_buff() -> BuffData:
    return BuffData(
        id=MARK_BUFF_ID,
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=-1,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.DEBUFF,
        description="",
    )


def _reactive_effect(
    trigger: PassiveSkillTrigger,
    target_type: PassiveSkillTargetType,
) -> PassiveSkillData:
    return PassiveSkillData(
        id=EFFECT_ID,
        trigger=trigger,
        target_type=target_type,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=MARK_BUFF_ID,
                buff_add_timing=None,
            )
        ],
        description="",
    )


def _make_context(
    trigger: PassiveSkillTrigger = PassiveSkillTrigger.ON_ENEMY_MOVE,
    target_type: PassiveSkillTargetType = PassiveSkillTargetType.FIELD_SUBJECT,
) -> BattlefieldContext:
    ctx = BattlefieldContext(
        buff_dict={MARK_BUFF_ID: _mark_buff()},
        skill_dict={},
        passive_skill_dict={EFFECT_ID: _reactive_effect(trigger, target_type)},
    )
    ctx.add_character(
        get_test_preset("아군_1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군_2"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군_1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx


def _manager(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


def _has_mark(ctx: BattlefieldContext, name: str) -> bool:
    return ctx.buff_container.get_buff(CharacterId(name), MARK_BUFF_ID) is not None


def _move_ally(ctx: BattlefieldContext, name: str = "아군_1") -> None:
    manager = _manager(ctx)
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.process_command(parse_character_command(CharacterId(name), "[이동/2]", ctx))


class TestOnMove:
    def test_mover_is_marked(self):
        ctx = _make_context()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        _move_ally(ctx)

        assert _has_mark(ctx, "아군_1")

    def test_others_are_not_marked(self):
        """FIELD_SUBJECT는 사건 당사자만 대상으로 삼는다."""
        ctx = _make_context()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        _move_ally(ctx)

        assert not _has_mark(ctx, "아군_2")
        assert not _has_mark(ctx, "적군_1")

    def test_nothing_happens_without_the_effect(self):
        ctx = _make_context()

        _move_ally(ctx)

        assert not _has_mark(ctx, "아군_1")

    def test_removed_effect_stops_reacting(self):
        ctx = _make_context()
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
        ctx.remove_field_effect(EFFECT_ID)

        _move_ally(ctx)

        assert not _has_mark(ctx, "아군_1")


class TestSubjectFactionGating:
    """필드 범위가 사건 당사자의 진영을 가린다. required_faction은 훅마다
    의미가 달라(이동은 foe_faction) 필드 효과 기준으로 쓸 수 없다."""

    def test_ally_side_scope_reacts_to_ally_move(self):
        ctx = _make_context(
            target_type=PassiveSkillTargetType.FIELD_ALLY_SIDE,
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        _move_ally(ctx)

        # 범위가 진영 전체이므로 이동하지 않은 같은 진영도 함께 받는다.
        assert _has_mark(ctx, "아군_1")
        assert _has_mark(ctx, "아군_2")
        assert not _has_mark(ctx, "적군_1")

    def test_enemy_side_scope_ignores_ally_move(self):
        ctx = _make_context(
            target_type=PassiveSkillTargetType.FIELD_ENEMY_SIDE,
        )
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)

        _move_ally(ctx)

        assert not _has_mark(ctx, "아군_1")
        assert not _has_mark(ctx, "적군_1")


class TestExistingPassivesUnaffected:
    def test_character_passive_still_uses_holder_faction(self):
        """홀더가 있는 기존 반응형 패시브의 판정은 그대로여야 한다 —
        적이 이동할 때 반대 진영 홀더가 반응하는 구조다."""
        passive = PassiveSkillData(
            id="PassiveSkill",
            trigger=PassiveSkillTrigger.ON_ENEMY_MOVE,
            target_type=PassiveSkillTargetType.ATTACKER_OR_TARGET,
            effects=[
                SkillEffectAddBuff(
                    value_source=None,
                    value=None,
                    value_type=None,
                    buff_id=MARK_BUFF_ID,
                    buff_add_timing=None,
                )
            ],
            description="",
        )
        ctx = BattlefieldContext(
            buff_dict={MARK_BUFF_ID: _mark_buff()},
            skill_dict={},
            passive_skill_dict={"PassiveSkill": passive},
        )
        ctx.add_character(
            get_test_preset("감시자", passive_skill_id="PassiveSkill"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("이동자"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )

        _move_ally(ctx, "이동자")

        assert _has_mark(ctx, "이동자")
