"""적층형 사용 여부별 보정: 적층형 버프/디버프를 부여할 때는 스택을 더 쌓고,
적층형을 전혀 쓰지 않는 캐릭터는 대미지가 늘어난다.

걸려 있는 동안 유지되는 상태라 필드 효과로 건다. 스택은 스킬·패시브 어느
경로로 부여하든 붙고, 대미지는 캐릭터 단위로 판정한다.
"""

from dataclasses import replace

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
from battle.objects.skill import effects
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectDamage,
    SkillEffectExtraStackBonus,
    SkillEffectNonStackerDamageBonus,
)
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

EFFECT_ID = "FieldEffect"
STACK_BUFF_ID = "StackDebuff"
PLAIN_BUFF_ID = "PlainDebuff"
REF_BUFF_ID = "RefDebuff"
STACK_PASSIVE_ID = "PassiveSkill"

STACKER = CharacterId("시전자_1")
NON_STACKER = CharacterId("시전자_2")
PASSIVE_STACKER = CharacterId("시전자_3")
FOE = CharacterId("적군")


def _buff(buff_id: str, max_stack, reference_buff_id=None) -> BuffData:
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
        reference_buff_id=reference_buff_id,
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


def _skill(skill_id: str, *skill_effects) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=list(skill_effects),
        description="",
    )


BONUS_EFFECT = PassiveSkillData(
    id=EFFECT_ID,
    trigger=PassiveSkillTrigger.BATTLE_START,
    target_type=PassiveSkillTargetType.FIELD_ALLY_SIDE,
    effects=[
        SkillEffectExtraStackBonus(None, 1, None, None, None),
        SkillEffectNonStackerDamageBonus(None, 10, None, None, None),
    ],
    description="",
)

# 행동할 때마다 상대에게 적층형 디버프를 거는 패시브.
STACK_PASSIVE = PassiveSkillData(
    id=STACK_PASSIVE_ID,
    trigger=PassiveSkillTrigger.ON_ACTION,
    target_type=PassiveSkillTargetType.ATTACKER_OR_TARGET,
    effects=[_add(STACK_BUFF_ID)],
    description="",
)

SKILLS = {
    "스킬_1": _skill("스킬_1", _damage()),
    "스킬_2": _skill("스킬_2", _damage(), _add(STACK_BUFF_ID)),
    "스킬_3": _skill("스킬_3", _damage(), _add(PLAIN_BUFF_ID)),
    "스킬_4": _skill("스킬_4", _add(REF_BUFF_ID)),
}


def _setup(with_effect: bool = True) -> tuple[BattlefieldContext, RoundManager]:
    ctx = BattlefieldContext(
        buff_dict={
            STACK_BUFF_ID: _buff(STACK_BUFF_ID, max_stack=10),
            PLAIN_BUFF_ID: _buff(PLAIN_BUFF_ID, max_stack=None),
            REF_BUFF_ID: _buff(
                REF_BUFF_ID, max_stack=None, reference_buff_id=STACK_BUFF_ID
            ),
        },
        skill_dict=SKILLS,
        passive_skill_dict={EFFECT_ID: BONUS_EFFECT, STACK_PASSIVE_ID: STACK_PASSIVE},
    )
    for i, (char_id, skills, passive) in enumerate(
        (
            (STACKER, ("스킬_1", "스킬_2"), None),
            (NON_STACKER, ("스킬_1", "스킬_3"), None),
            (PASSIVE_STACKER, ("스킬_1",), STACK_PASSIVE_ID),
        )
    ):
        preset = get_test_preset(char_id.name, atk=100, passive_skill_id=passive)
        ctx.add_character(
            replace(preset, skill_id_list=[*skills, "", ""][:3]),
            FactionType.ALLY,
            BattlefieldColumnIndex(i),
        )
    ctx.add_character(
        get_test_preset(FOE.name, max_hp=10000),
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


def _use(ctx, manager, user: CharacterId, text: str) -> int:
    before = ctx.characters[FOE].status.curr_hp
    manager.process_command(parse_character_command(user, text, ctx))
    return before - ctx.characters[FOE].status.curr_hp


def _stack(ctx) -> int:
    return ctx.get_buff_stack(FOE, STACK_BUFF_ID)


class TestStackerJudgement:
    def test_skill_or_passive_with_stack_buff_makes_a_stacker(self):
        ctx, _ = _setup()

        assert ctx.uses_stacking_buffs(STACKER)
        assert ctx.uses_stacking_buffs(PASSIVE_STACKER)
        assert not ctx.uses_stacking_buffs(NON_STACKER)

    def test_buff_referencing_a_stack_buff_counts(self):
        ctx, _ = _setup()
        ctx.characters[NON_STACKER].skills.append(
            SKILLS["스킬_4"].to_skill_instance(ctx, NON_STACKER)
        )

        assert ctx.uses_stacking_buffs(NON_STACKER)


class TestExtraStack:
    def test_skill_applied_stack_gets_extra(self):
        ctx, manager = _setup()

        _use(ctx, manager, STACKER, f"[스킬_2/{FOE.name}]")

        assert _stack(ctx) == 2

    def test_passive_applied_stack_gets_extra(self):
        ctx, manager = _setup()

        _use(ctx, manager, PASSIVE_STACKER, f"[스킬_1/{FOE.name}]")

        assert _stack(ctx) == 2

    def test_without_effect_single_stack(self):
        ctx, manager = _setup(with_effect=False)

        _use(ctx, manager, STACKER, f"[스킬_2/{FOE.name}]")

        assert _stack(ctx) == 1


class TestNonStackerDamage:
    def test_non_stacker_skill_deals_more_damage(self):
        ctx, manager = _setup()

        assert _use(ctx, manager, NON_STACKER, f"[스킬_1/{FOE.name}]") == 110

    def test_non_stacker_basic_attack_gets_the_bonus(self):
        ctx, manager = _setup()

        _use(ctx, manager, NON_STACKER, f"[공격/{FOE.name}]")

        displays = [e.roll_display or "" for r in ctx.results for e in r.log_entries]
        assert any("필드 효과" in d for d in displays)

    def test_stacker_gets_no_bonus_even_with_a_non_stack_skill(self):
        ctx, manager = _setup()

        assert _use(ctx, manager, STACKER, f"[스킬_1/{FOE.name}]") == 100

    def test_without_effect_no_bonus(self):
        ctx, manager = _setup(with_effect=False)

        assert _use(ctx, manager, NON_STACKER, f"[스킬_1/{FOE.name}]") == 100

    def test_removing_the_field_effect_reverts_both_bonuses(self):
        ctx, manager = _setup()
        ctx.remove_field_effect(EFFECT_ID)

        assert _use(ctx, manager, NON_STACKER, f"[스킬_1/{FOE.name}]") == 100
        _use(ctx, manager, STACKER, f"[스킬_2/{FOE.name}]")
        assert _stack(ctx) == 1


def test_old_class_names_still_load_from_the_sheet():
    """시트의 effect_N을 새 이름으로 바꾸기 전에 재기동해도 읽혀야 한다."""
    assert effects.SkillEffectStackSkillBonus is SkillEffectExtraStackBonus
    assert effects.SkillEffectPlainSkillDamageBonus is SkillEffectNonStackerDamageBonus
