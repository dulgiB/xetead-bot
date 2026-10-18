"""스킬 종류별 보정: 적층형 버프/디버프를 부여하는 스킬은 스택을 더 얹고,
그렇지 않은 스킬은 대미지가 늘어난다.

걸려 있는 동안 유지되는 상태라 필드 효과로 걸며, 기본 공격은 스킬이 아니라
대상이 아니다.
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
    ValueSourceType,
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
    SkillEffectDamage,
    SkillEffectPlainSkillDamageBonus,
    SkillEffectStackSkillBonus,
)
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

EFFECT_ID = "FieldEffect"
STACK_BUFF_ID = "StackDebuff"
PLAIN_BUFF_ID = "PlainDebuff"

USER = CharacterId("시전자")
FOE = CharacterId("적군")


def _buff(buff_id: str, max_stack) -> BuffData:
    return BuffData(
        id=buff_id,
        buff_class_name="BuffReceivedDamage",
        duration_turn_value=3,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=0,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.DEBUFF,
        description="",
        max_stack=max_stack,
    )


def _damage() -> SkillEffectDamage:
    # 고정 대미지는 배율 보정을 받지 않으므로 공격력 계수로 만든다.
    return SkillEffectDamage(
        ValueSourceType.STAT_ATK, 100, SkillValueType.PERCENT, None, None
    )


def _add(buff_id: str) -> SkillEffectAddBuff:
    return SkillEffectAddBuff(
        value_source=None,
        value=None,
        value_type=None,
        buff_id=buff_id,
        buff_add_timing=None,
    )


def _skill(skill_id: str, *effects) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=list(effects),
        description="",
    )


def _bonus_effect() -> PassiveSkillData:
    return PassiveSkillData(
        id=EFFECT_ID,
        trigger=PassiveSkillTrigger.BATTLE_START,
        target_type=PassiveSkillTargetType.FIELD_ALLY_SIDE,
        effects=[
            SkillEffectStackSkillBonus(None, 1, None, None, None),
            SkillEffectPlainSkillDamageBonus(None, 10, None, None, None),
        ],
        description="",
    )


SKILLS = {
    "스킬_1": _skill("스킬_1", _damage()),
    "스킬_2": _skill("스킬_2", _damage(), _add(STACK_BUFF_ID)),
    "스킬_3": _skill("스킬_3", _damage(), _add(PLAIN_BUFF_ID)),
}


def _setup(with_effect: bool = True) -> tuple[BattlefieldContext, RoundManager]:
    ctx = BattlefieldContext(
        buff_dict={
            STACK_BUFF_ID: _buff(STACK_BUFF_ID, max_stack=10),
            PLAIN_BUFF_ID: _buff(PLAIN_BUFF_ID, max_stack=None),
        },
        skill_dict=SKILLS,
        passive_skill_dict={EFFECT_ID: _bonus_effect()},
    )
    ctx.add_character(
        get_test_preset(
            USER.name,
            atk=100,
            skill_1_id="스킬_1",
            skill_2_id="스킬_2",
            skill_3_id="스킬_3",
        ),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset(FOE.name, max_hp=1000),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    if with_effect:
        ctx.add_field_effect(EFFECT_ID, FieldEffectSource.ADMIN)
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    return ctx, manager


def _use(ctx: BattlefieldContext, manager: RoundManager, text: str) -> int:
    before = ctx.characters[FOE].status.curr_hp
    manager.process_command(parse_character_command(USER, text, ctx))
    return before - ctx.characters[FOE].status.curr_hp


class TestPlainSkillDamage:
    def test_skill_without_stack_buff_deals_more_damage(self):
        ctx, manager = _setup()

        assert _use(ctx, manager, f"[스킬_1/{FOE.name}]") == 110

    def test_non_stack_buff_does_not_count_as_stack_skill(self):
        ctx, manager = _setup()

        assert _use(ctx, manager, f"[스킬_3/{FOE.name}]") == 110

    def test_basic_attack_is_not_a_skill(self):
        ctx, manager = _setup()

        # 굴림이 섞이므로 수치가 아니라 보정 라벨이 붙지 않았는지로 본다.
        manager.process_command(
            parse_character_command(USER, f"[공격/{FOE.name}]", ctx)
        )
        labels = [
            entry.roll_display or ""
            for result in ctx.results
            for entry in result.log_entries
        ]
        assert not any("필드 효과" in label for label in labels)

    def test_without_effect_no_bonus(self):
        ctx, manager = _setup(with_effect=False)

        assert _use(ctx, manager, f"[스킬_1/{FOE.name}]") == 100


class TestStackSkill:
    def test_stack_buff_gets_extra_stack(self):
        ctx, manager = _setup()

        _use(ctx, manager, f"[스킬_2/{FOE.name}]")

        assert ctx.get_buff_stack(FOE, STACK_BUFF_ID) == 2

    def test_stack_skill_gets_no_damage_bonus(self):
        ctx, manager = _setup()

        assert _use(ctx, manager, f"[스킬_2/{FOE.name}]") == 100

    def test_without_effect_single_stack(self):
        ctx, manager = _setup(with_effect=False)

        _use(ctx, manager, f"[스킬_2/{FOE.name}]")

        assert ctx.get_buff_stack(FOE, STACK_BUFF_ID) == 1

    def test_removing_the_field_effect_reverts_both_bonuses(self):
        ctx, manager = _setup()
        ctx.remove_field_effect(EFFECT_ID)

        assert _use(ctx, manager, f"[스킬_1/{FOE.name}]") == 100
        _use(ctx, manager, f"[스킬_2/{FOE.name}]")
        assert ctx.get_buff_stack(FOE, STACK_BUFF_ID) == 1

    def test_enemies_outside_the_scope_get_nothing(self):
        ctx, _ = _setup()

        status = ctx.characters[FOE].status
        assert status.stack_skill_bonus == 0
        assert status.plain_skill_damage_bonus == 0
