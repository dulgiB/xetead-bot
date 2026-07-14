"""
test_buff_stacking.py
적층형(스택) 버프 지원과 관련 기능(CONSUMED_BUFF_STACK, ALLY_DAMAGED 관전 훅,
SkillEffectConsumeStackForDamage, SkillEffectHealAndFillBuffStack, BuffCurse의
전투 종료 훅)에 대한 단위 테스트 모음.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectConsumeStackForDamage,
    SkillEffectDamage,
    SkillEffectHealAndFillBuffStack,
)
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


def make_curse_data(max_stack: int = 10) -> BuffData:
    return BuffData(
        id="재앙",
        description="",
        buff_class_name="BuffCurse",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=None,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        max_stack=max_stack,
    )


def setup_ally_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


def setup_enemy_pre_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


class TestBuffStackAccumulation:
    """BuffContainer.add()의 적층 clamp 동작."""

    def test_stack_accumulates_up_to_max(self):
        curse = make_curse_data(max_stack=10)
        ctx = BattlefieldContext(buff_dict={"재앙": curse}, skill_dict={})
        holder = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )

        ctx.buff_container.add(
            BuffAddData(
                given_by=holder, applied_to=holder, buff_id="재앙", stack_value=4
            )
        )
        assert ctx.get_buff_stack(holder, "재앙") == 4

        ctx.buff_container.add(
            BuffAddData(
                given_by=holder, applied_to=holder, buff_id="재앙", stack_value=9
            )
        )
        # 4 + 9 = 13 이지만 max_stack=10에서 clamp 되어야 한다.
        assert ctx.get_buff_stack(holder, "재앙") == 10

    def test_non_stackable_buff_reapply_is_ignored(self):
        """max_stack이 없는 기존 버프는 재부여 시 그대로 무시되는 기존 동작을 유지한다."""
        buff = BuffData(
            id="공격력 증가",
            description="",
            buff_class_name="BuffAtk",
            duration_turn_value=3,
            duration_count_value=None,
            duration_count_deduct_condition=None,
            value_type=ValueType.INTEGER,
            value=5,
            condition_=None,
            condition_value=None,
            is_debuff=False,
        )
        ctx = BattlefieldContext(buff_dict={"공격력 증가": buff}, skill_dict={})
        holder = CharacterId("대상")
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )

        ctx.buff_container.add(
            BuffAddData(given_by=holder, applied_to=holder, buff_id="공격력 증가")
        )
        ctx.buff_container.add(
            BuffAddData(given_by=holder, applied_to=holder, buff_id="공격력 증가")
        )
        buffs = ctx.buff_container.get_buffs_by(holder, None)
        assert len(buffs) == 1


class TestConsumeStackForDamage:
    """SkillEffectConsumeStackForDamage: 스택 소모 clamp + CONSUMED_BUFF_STACK
    기반 대미지 가산, ConsumedBuffStackCountCondition 기반 조건부 버프 부여."""

    def _make_context(self):
        curse = make_curse_data()
        taunt = BuffData(
            id="도발_1",
            description="",
            buff_class_name="BuffTaunt",
            duration_turn_value=1,
            duration_count_value=None,
            duration_count_deduct_condition=None,
            value_type=None,
            value=0,
            condition_=None,
            condition_value=None,
            is_debuff=False,
        )
        skill = SkillData(
            id="저주 폭발",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=2,
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
                ),
                SkillEffectConsumeStackForDamage(
                    value_source=ValueSourceType.CONSUMED_BUFF_STACK,
                    value=300,
                    value_type=ValueType.PERCENT,
                    buff_id="재앙",
                    buff_add_timing=None,
                    buff_stack_cap=5,
                ),
                # 실제 데이터 로딩 시엔 parse_skill_effect()가 condition_class_name=
                # "ConsumedBuffStackCountCondition"을 아래 게이트 필드로 변환해준다.
                # 여기서는 효과를 직접 구성하므로 변환된 형태를 바로 사용한다.
                SkillEffectAddBuff(
                    value_source=None,
                    value=None,
                    value_type=None,
                    buff_id="도발_1",
                    buff_add_timing=None,
                    gate_value_source=ValueSourceType.CONSUMED_BUFF_STACK,
                    gate_value=3,
                ),
            ],
            description="",
        )
        ctx = BattlefieldContext(
            buff_dict={"재앙": curse, "도발_1": taunt},
            skill_dict={"저주 폭발": skill},
        )
        manager = setup_ally_phase(ctx)
        caster = CharacterId("Catastrophe")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Catastrophe", skill_1_id="저주 폭발"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=200), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        return ctx, manager, caster, target

    def test_bonus_damage_scales_with_consumed_stack_and_taunt_applied(self):
        """4스택 보유 → 4 소모(cap 5는 clamp) → 보너스 대미지 4*3=12,
        기본 10 포함 총 22. 소모량 3 이상이므로 도발도 함께 부여된다."""
        ctx, manager, caster, target = self._make_context()
        ctx.buff_container.add(
            BuffAddData(given_by=caster, applied_to=target, buff_id="재앙", stack_value=4)
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[스킬/저주 폭발/적군]")
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 22
        assert ctx.get_buff_stack(target, "재앙") == 0
        assert any(
            b.id == "도발_1" for b in ctx.buff_container.get_buffs_by(target, None)
        )

    def test_taunt_not_applied_when_consumed_below_threshold(self):
        """2스택만 보유 → 2 소모(임계값 3 미만) → 보너스 대미지 2*3=6, 총 16.
        도발은 부여되지 않아야 한다."""
        ctx, manager, caster, target = self._make_context()
        ctx.buff_container.add(
            BuffAddData(given_by=caster, applied_to=target, buff_id="재앙", stack_value=2)
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[스킬/저주 폭발/적군]")
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 16
        assert not any(
            b.id == "도발_1" for b in ctx.buff_container.get_buffs_by(target, None)
        )


class TestAllyDamagedHook:
    """ALLY_DAMAGED 타이밍 패시브: 같은 열(자신 포함)의 피격에만 반응한다."""

    def _make_passive_context(self, condition_class_name=None):
        curse = make_curse_data()
        passive = PassiveSkillData(
            id="재앙 축적",
            trigger=PassiveSkillTrigger.ALLY_DAMAGED,
            target_type=PassiveSkillTargetType.SELF,
            effects=[
                SkillEffectAddBuff(
                    value_source=None,
                    value=None,
                    value_type=None,
                    buff_id="재앙",
                    buff_add_timing=None,
                    buff_stack_cap=1,
                    condition_class_name=condition_class_name,
                )
            ],
            description="",
        )
        ctx = BattlefieldContext(
            buff_dict={"재앙": curse}, skill_dict={}, passive_skill_dict={"재앙 축적": passive}
        )
        return ctx

    def test_stack_gained_when_same_column_ally_damaged(self):
        ctx = self._make_passive_context()
        manager = setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", passive_skill_id="재앙 축적"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("동료"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/동료]")
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 1

    def test_no_stack_when_different_column_ally_damaged(self):
        ctx = self._make_passive_context()
        manager = setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", passive_skill_id="재앙 축적"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("무관한아군"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(1)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/무관한아군]")
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 0

    def test_extra_stack_only_when_holder_itself_damaged(self):
        """HolderWasAttackedCondition: 자신이 맞았을 때만 추가로 반응."""
        ctx = self._make_passive_context(condition_class_name="HolderWasAttackedCondition")
        manager = setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", passive_skill_id="재앙 축적"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("동료"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군2"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군1"), "[공격/동료]")
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 0

        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        ctx.on_finish_round()
        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("적군2"), "[공격/Catastrophe]")
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 1


class TestSkillEffectHealAndFillBuffStack:
    def test_heal_fills_target_and_overflow_heals_self(self):
        curse = make_curse_data()
        skill = SkillData(
            id="재앙 나눔",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=3,
            effects=[
                SkillEffectHealAndFillBuffStack(
                    value_source=None,
                    value=500,
                    value_type=ValueType.PERCENT,
                    buff_id="재앙",
                    buff_add_timing=None,
                )
            ],
            description="",
        )
        ctx = BattlefieldContext(
            buff_dict={"재앙": curse}, skill_dict={"재앙 나눔": skill}
        )
        manager = setup_ally_phase(ctx)
        caster = CharacterId("Catastrophe")
        ally = CharacterId("아군")
        ctx.add_character(
            get_test_preset("Catastrophe", skill_1_id="재앙 나눔", initial_hp=90, max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군", initial_hp=84, max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.buff_container.add(
            BuffAddData(given_by=caster, applied_to=caster, buff_id="재앙", stack_value=6)
        )

        # space = 10-6=4 -> heal_amount = 4*5=20. 아군은 84->100(16 흡수),
        # 초과분 4는 Catastrophe 자신에게: 90+4=94.
        manager.process_command(
            parse_character_command(caster, "[스킬/재앙 나눔/아군]")
        )

        assert ctx.characters[ally].status.curr_hp == 100
        assert ctx.characters[caster].status.curr_hp == 94
        assert ctx.get_buff_stack(caster, "재앙") == 10


class TestBuffCurseBattleEnd:
    def test_battle_end_reduces_hp_by_triple_stack(self):
        curse = make_curse_data()
        ctx = BattlefieldContext(buff_dict={"재앙": curse}, skill_dict={})
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            BuffAddData(given_by=catastrophe_id, applied_to=catastrophe_id, buff_id="재앙", stack_value=6)
        )

        ctx.on_battle_end()

        assert ctx.characters[catastrophe_id].status.curr_hp == 100 - 6 * 3

    def test_curse_not_removed_by_round_end_or_debuff_removal(self):
        curse = make_curse_data()
        ctx = BattlefieldContext(buff_dict={"재앙": curse}, skill_dict={})
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.buff_container.add(
            BuffAddData(given_by=catastrophe_id, applied_to=catastrophe_id, buff_id="재앙", stack_value=3)
        )

        for _ in range(5):
            ctx.on_finish_round()

        buff = ctx.get_buff_instance(catastrophe_id, "재앙")
        assert buff is not None
        assert buff.stack_count == 3
        assert buff.is_debuff is False
