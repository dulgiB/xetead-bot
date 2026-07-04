"""
test_buffs.py
각 버프 클래스의 동작을 검증하는 단위 테스트 모음.

각 테스트는 독립적인 컨텍스트와 캐릭터를 사용하므로 순서에 무관하게 실행 가능하다.
"""

from typing import Optional

import pytest
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
    BuffApplyTiming,
    BuffCountDeductCondition,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import (
    SkillEffectAddBuff,
    SkillEffectDamage,
    SkillEffectHeal,
)
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


def make_context(
    *buff_datas: BuffData, skill_dict: dict = None, passive_skill_dict: dict = None
) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={b.id: b for b in buff_datas},
        skill_dict=skill_dict or {},
        passive_skill_dict=passive_skill_dict,
    )


def make_buff_data(
    buff_id: str,
    buff_class_name: str,
    *,
    duration_turn_value: Optional[int] = 3,
    duration_count_value: Optional[int] = None,
    duration_count_deduct_condition: Optional[BuffCountDeductCondition] = None,
    value_type: ValueType | None = None,
    value: int = 0,
    condition_: str | None = None,
    condition_value: int | None = None,
    is_debuff: bool = False,
) -> BuffData:
    return BuffData(
        id=buff_id,
        description="",
        buff_class_name=buff_class_name,
        duration_turn_value=duration_turn_value,
        duration_count_value=duration_count_value,
        duration_count_deduct_condition=duration_count_deduct_condition,
        value_type=value_type,
        value=value,
        condition_=condition_,
        condition_value=condition_value,
        is_debuff=is_debuff,
    )


def make_buff_skill(
    skill_id: str,
    buff_id: str,
    *,
    timing_if_enemy_skill: Optional[RoundPhaseType] = None,
) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=buff_id,
                buff_add_timing=timing_if_enemy_skill,
            )
        ],
        description="",
    )


def setup_enemy_pre_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


def setup_ally_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


class TestBuffAtk:
    """BuffAtk: 공격 시 공격자의 ATK 스탯에 정수 보너스를 추가한다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data(
            "공격력 증가", "BuffAtk", value_type=ValueType.INTEGER, value=5
        )
        skill = make_buff_skill("버프 스킬", "공격력 증가")
        return make_context(buff, skill_dict={"버프 스킬": skill})

    def test_atk_buff_present_after_skill(self, ctx):
        """스킬 사용 후 대상에게 BuffAtk이 부여된다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="버프 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/버프 스킬/대상]")
        )

        buffs = ctx.buff_container.get_buffs_by(
            CharacterId("대상"), BuffApplyTiming.ON_ACTION
        )
        assert any(b.value == 5 and b.id == "공격력 증가" for b in buffs)

    def test_atk_buff_increases_damage(self, ctx):
        """BuffAtk을 보유한 캐릭터의 공격 대미지 기댓값이 올라야 한다."""
        buff = make_buff_data(
            "공격력 증가", "BuffAtk", value_type=ValueType.INTEGER, value=10
        )
        skill = make_buff_skill("버프 스킬", "공격력 증가")
        ctx = make_context(buff, skill_dict={"버프 스킬": skill})
        manager = setup_ally_phase(ctx)

        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="버프 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수", atk=1),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        # 버프 없이 공격
        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]")
        )
        hp_after_no_buff = ctx.characters[CharacterId("적군")].status.curr_hp

        # 버프 부여
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/버프 스킬/공격수]")
        )
        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]")
        )
        hp_after_buff = ctx.characters[CharacterId("적군")].status.curr_hp

        damage_no_buff = 100 - hp_after_no_buff
        damage_with_buff = hp_after_no_buff - hp_after_buff
        assert damage_with_buff > damage_no_buff


class TestBuffGivenDamage:
    """BuffGivenDamage: 공격 시 해당 캐릭터가 주는 대미지에 수정자를 적용한다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data(
            "대미지 증가", "BuffGivenDamage", value_type=ValueType.PERCENT, value=50
        )
        skill = make_buff_skill("대미지 증가 스킬", "대미지 증가")
        return make_context(buff, skill_dict={"대미지 증가 스킬": skill})

    def test_given_damage_buff_increases_damage(self, ctx):
        """BuffGivenDamage를 받은 후 공격하면 더 큰 대미지를 입힌다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="대미지 증가 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수", atk=1),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        # 버프 없이 공격
        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]")
        )
        hp_after_no_buff = ctx.characters[CharacterId("적군")].status.curr_hp
        damage_no_buff = 100 - hp_after_no_buff

        # 버프 부여 후 공격
        manager.process_command(
            parse_character_command(
                CharacterId("버퍼"), "[스킬/대미지 증가 스킬/공격수]"
            )
        )

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]")
        )
        hp_after_buff = ctx.characters[CharacterId("적군")].status.curr_hp
        damage_with_buff = hp_after_no_buff - hp_after_buff

        assert damage_with_buff > damage_no_buff

    def test_given_damage_buff_applied_once_per_aoe_action(self):
        """광역 스킬로 여러 대상을 동시에 타격해도, 공격자 측 버프는 대상 하나당이
        아니라 행동 1회당 한 번만 적용/차감되어야 한다."""
        buff = make_buff_data(
            "대미지 증가",
            "BuffGivenDamage",
            duration_turn_value=None,
            duration_count_value=3,
            duration_count_deduct_condition=BuffCountDeductCondition.ON_ATTACK,
            value_type=ValueType.INTEGER,
            value=10,
        )
        aoe_skill = SkillData(
            id="광역기",
            target_rule="SkillTargetRuleColumn",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
        ctx = make_context(buff, skill_dict={"광역기": aoe_skill})
        manager = setup_ally_phase(ctx)

        attacker_id = CharacterId("공격수")
        ctx.add_character(
            get_test_preset("공격수", skill_1_id="광역기"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군2"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        ctx.buff_container.add(
            BuffAddData(
                given_by=attacker_id, applied_to=attacker_id, buff_id="대미지 증가"
            )
        )

        manager.process_command(
            parse_character_command(attacker_id, "[스킬/광역기/1열]")
        )

        # 고정 5 대미지 + 버프 고정 +10 = 15. 대상 수만큼 중복 적용되면 25가 된다.
        assert ctx.characters[CharacterId("적군1")].status.curr_hp == 100 - 15
        assert ctx.characters[CharacterId("적군2")].status.curr_hp == 100 - 15

        buffs = ctx.buff_container.get_buffs_by(attacker_id, BuffApplyTiming.ON_ACTION)
        assert len(buffs) == 1
        # 대상이 둘이어도 행동은 1회이므로 count는 1만 소모되어야 한다.
        assert buffs[0].duration.remaining_count == 2


class TestBuffReceivedDamage:
    """BuffReceivedDamage: 피격 시 해당 캐릭터가 받는 대미지에 수정자를 적용한다."""

    @pytest.fixture
    def ctx_damage_up(self):
        buff = make_buff_data(
            "피해 증가", "BuffReceivedDamage", value_type=ValueType.PERCENT, value=50
        )
        skill = make_buff_skill("취약 스킬", "피해 증가")
        return make_context(buff, skill_dict={"취약 스킬": skill})

    @pytest.fixture
    def ctx_damage_down(self):
        buff = make_buff_data(
            "피해 감소", "BuffReceivedDamage", value_type=ValueType.PERCENT, value=-50
        )
        skill = make_buff_skill("방어 스킬", "피해 감소")
        return make_context(buff, skill_dict={"방어 스킬": skill})

    def test_received_damage_buff_increases_damage_taken(self, ctx_damage_up):
        """받는 대미지 증가 버프를 받은 캐릭터는 더 큰 피해를 입는다."""
        ctx = ctx_damage_up
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="취약 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군 A"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군 B"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/취약 스킬/적군 A]")
        )

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 A]")
        )
        damage_to_buffed = 100 - ctx.characters[CharacterId("적군 A")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 B]")
        )
        damage_to_normal = 100 - ctx.characters[CharacterId("적군 B")].status.curr_hp

        assert damage_to_buffed > damage_to_normal

    def test_received_damage_buff_decreases_damage_taken(self, ctx_damage_down):
        """받는 대미지 감소 버프를 받은 캐릭터는 더 작은 피해를 입는다."""
        ctx = ctx_damage_down
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="방어 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군 A", max_hp=100),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군 B", max_hp=100),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/방어 스킬/적군 A]")
        )

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 A]")
        )
        damage_to_buffed = 100 - ctx.characters[CharacterId("적군 A")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 B]")
        )
        damage_to_normal = 100 - ctx.characters[CharacterId("적군 B")].status.curr_hp

        assert damage_to_buffed <= damage_to_normal


class TestBuffNoDamage:
    """BuffNoDamage: 피격 시 받는 대미지를 0으로 만든다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data("무적", "BuffNoDamage")
        skill = make_buff_skill("무적 스킬", "무적")
        return make_context(buff, skill_dict={"무적 스킬": skill})

    def test_no_damage_when_invincible(self, ctx):
        """무적 버프를 받은 캐릭터는 공격을 받아도 HP가 변하지 않는다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="무적 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        # 적군에게 무적 부여
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/무적 스킬/적군]")
        )

        initial_hp = ctx.characters[CharacterId("적군")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]")
        )

        assert ctx.characters[CharacterId("적군")].status.curr_hp == initial_hp


class TestBuffNoHeal:
    """BuffNoHeal: 회복 시 회복량을 0으로 만든다."""

    @pytest.fixture
    def ctx(self):
        debuff = make_buff_data("회복 불가", "BuffNoHeal")
        debuff_skill = make_buff_skill("회복 불가 스킬", "회복 불가")
        from battle.objects.define import ValueSourceType

        heal_skill = SkillData(
            id="회복 스킬",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=2,
            effects=[
                SkillEffectHeal(
                    ValueSourceType.FIXED, 30, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
        return make_context(
            debuff,
            skill_dict={"회복 불가 스킬": debuff_skill, "회복 스킬": heal_skill},
        )

    def test_no_heal_when_debuffed(self, ctx):
        """회복 불가 디버프를 받은 캐릭터는 회복 스킬을 받아도 HP가 변하지 않는다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("디버퍼", skill_1_id="회복 불가 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("힐러", skill_2_id="회복 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("환자", initial_hp=50),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )

        # 환자에게 회복 불가 부여
        manager.process_command(
            parse_character_command(CharacterId("디버퍼"), "[스킬/회복 불가 스킬/환자]")
        )
        initial_hp = ctx.characters[CharacterId("환자")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("힐러"), "[스킬/회복 스킬/환자]")
        )

        assert ctx.characters[CharacterId("환자")].status.curr_hp == initial_hp


class TestBuffDamageOverTime:
    """BuffDamageOverTime: 라운드 종료 시 고정 대미지를 입힌다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data("독", "BuffDamageOverTime", value=10)
        skill = make_buff_skill(
            "독 스킬", "독", timing_if_enemy_skill=RoundPhaseType.ENEMY_PRE_ACTION
        )
        return make_context(buff, skill_dict={"독 스킬": skill})

    def test_dot_damages_on_round_end(self, ctx):
        """도트 디버프를 받은 캐릭터는 라운드 종료 시 HP가 감소한다."""
        manager = setup_enemy_pre_phase(ctx)
        ctx.add_character(
            get_test_preset("독사", skill_1_id="독 스킬"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(
            parse_character_command(CharacterId("독사"), "[스킬/독 스킬/아군]")
        )
        initial_hp = ctx.characters[CharacterId("아군")].status.curr_hp

        ctx.on_finish_round()
        assert ctx.characters[CharacterId("아군")].status.curr_hp < initial_hp

    def test_dot_expires_after_duration(self, ctx):
        """도트 버프는 지속 턴수가 다 되면 제거된다."""
        manager = setup_enemy_pre_phase(ctx)
        ctx.add_character(
            get_test_preset("독사", skill_1_id="독 스킬"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        target_id = CharacterId("아군")

        manager.process_command(
            parse_character_command(CharacterId("독사"), "[스킬/독 스킬/아군]")
        )

        for i in range(3):
            ctx.on_finish_round()

        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ROUND_END)
        assert len(buffs) == 0


class TestBuffHealOverTime:
    """BuffHealOverTime: 라운드 종료 시 고정 회복량을 회복한다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data("재생", "BuffHealOverTime", value=20)
        skill = make_buff_skill("재생 스킬", "재생")
        return make_context(buff, skill_dict={"재생 스킬": skill})

    def test_hot_heals_on_round_end(self, ctx):
        """재생 버프를 받은 캐릭터는 라운드 종료 시 HP가 증가한다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("힐러", skill_1_id="재생 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("환자", initial_hp=50, max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        target_id = CharacterId("환자")

        manager.process_command(
            parse_character_command(CharacterId("힐러"), "[스킬/재생 스킬/환자]")
        )
        hp_after_buff = ctx.characters[target_id].status.curr_hp

        ctx.on_finish_round()

        assert ctx.characters[target_id].status.curr_hp > hp_after_buff

    def test_hot_does_not_exceed_max_hp(self, ctx):
        """재생 버프는 최대 체력을 초과하여 회복시키지 않는다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("힐러", skill_1_id="재생 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("환자", initial_hp=100, max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        target_id = CharacterId("환자")

        manager.process_command(
            parse_character_command(CharacterId("힐러"), "[스킬/재생 스킬/환자]")
        )
        ctx.on_finish_round()

        assert ctx.characters[target_id].status.curr_hp <= 100


class TestBuffTaunt:
    """BuffTaunt: 공격 시 공격 대상을 도발자로 강제 변경한다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data("도발", "BuffTaunt")
        skill = make_buff_skill("도발 스킬", "도발")
        return make_context(buff, skill_dict={"도발 스킬": skill})

    def test_taunt_redirects_attack(self, ctx):
        """도발 버프를 받은 캐릭터를 공격하면, 실제 대미지는 도발자에게 들어간다."""
        manager = setup_enemy_pre_phase(ctx)

        ctx.add_character(
            get_test_preset("도발자", skill_1_id="도발 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/공격수]")
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[스킬/도발 스킬/적군]")
        )

        hp_dealer_before = ctx.characters[CharacterId("공격수")].status.curr_hp
        hp_taunter_before = ctx.characters[CharacterId("도발자")].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.characters[CharacterId("공격수")].status.curr_hp == hp_dealer_before
        assert ctx.characters[CharacterId("도발자")].status.curr_hp < hp_taunter_before

    def test_taunt_redirects_skill_damage_and_attached_debuff(self):
        """도발받은 적이 대미지+디버프 스킬을 쓰면, 대미지뿐 아니라 딸린 디버프도
        도발자에게 함께 적용되어야 한다."""
        taunt_buff = make_buff_data("도발", "BuffTaunt")
        debuff = make_buff_data("디버프", "BuffNoDamage")
        taunt_skill = make_buff_skill("도발 스킬", "도발")
        # 적군 스킬: 대미지(POST) + 디버프(POST)
        enemy_skill = SkillData(
            id="저주 일격",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=2,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=10,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
                ),
                SkillEffectAddBuff(
                    value_source=None,
                    value=None,
                    value_type=None,
                    buff_id="디버프",
                    buff_add_timing=RoundPhaseType.ENEMY_POST_ACTION,
                ),
            ],
            description="",
        )
        ctx = make_context(
            taunt_buff,
            debuff,
            skill_dict={"도발 스킬": taunt_skill, "저주 일격": enemy_skill},
        )
        manager = setup_enemy_pre_phase(ctx)

        ctx.add_character(
            get_test_preset("도발자", skill_1_id="도발 스킬"),
            FactionType.ALLY, BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군", skill_1_id="저주 일격"),
            FactionType.ENEMY, BattlefieldColumnIndex(1),
        )

        # 적이 공격수에게 저주 일격 선언
        manager.process_command(
            parse_character_command(CharacterId("적군"), "[스킬/저주 일격/공격수]")
        )
        # 아군 페이즈: 도발자가 적을 도발
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[스킬/도발 스킬/적군]")
        )

        hp_dealer_before = ctx.characters[CharacterId("공격수")].status.curr_hp
        hp_taunter_before = ctx.characters[CharacterId("도발자")].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        # 대미지: 공격수 무사, 도발자 피격
        assert ctx.characters[CharacterId("공격수")].status.curr_hp == hp_dealer_before
        assert ctx.characters[CharacterId("도발자")].status.curr_hp < hp_taunter_before

        # 디버프도 도발자에게만 적용되고 공격수에게는 적용되지 않아야 한다.
        dealer_buffs = ctx.buff_container.get_buffs_by(
            CharacterId("공격수"), BuffApplyTiming.ON_ACTION
        )
        taunter_buffs = ctx.buff_container.get_buffs_by(
            CharacterId("도발자"), BuffApplyTiming.ON_ACTION
        )
        assert not any(b.id == "디버프" for b in dealer_buffs)
        assert any(b.id == "디버프" for b in taunter_buffs)


class TestBuffDuration:
    """버프 지속 시간(TURN/COUNT) 공통 동작 테스트."""

    def test_turn_duration_decrements_on_round_end(self):
        buff = make_buff_data(
            "테스트 버프", "BuffAtk", value_type=ValueType.INTEGER, value=1
        )
        skill = make_buff_skill("버프 스킬", "테스트 버프")
        ctx = make_context(buff, skill_dict={"버프 스킬": skill})
        manager = setup_ally_phase(ctx)

        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="버프 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/버프 스킬/대상]")
        )
        target_id = CharacterId("대상")

        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert buffs[0].duration.remaining_turns == 3

        ctx.on_finish_round()
        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert buffs[0].duration.remaining_turns == 2

    def test_turn_duration_buff_removed_after_expiry(self):
        buff = make_buff_data(
            "단기 버프",
            "BuffAtk",
            duration_turn_value=1,
            value_type=ValueType.INTEGER,
            value=1,
        )
        skill = make_buff_skill("버프 스킬", "단기 버프")
        ctx = make_context(buff, skill_dict={"버프 스킬": skill})
        manager = setup_ally_phase(ctx)

        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="버프 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/버프 스킬/대상]")
        )

        ctx.on_finish_round()

        buffs = ctx.buff_container.get_buffs_by(
            CharacterId("대상"), BuffApplyTiming.ON_ACTION
        )
        assert len(buffs) == 0

    def test_count_duration_buff_decrements_on_hit(self):
        buff = make_buff_data(
            "테스트 버프",
            "BuffAtk",
            duration_turn_value=None,
            duration_count_value=3,
            duration_count_deduct_condition=BuffCountDeductCondition.ON_HIT,
            value_type=ValueType.INTEGER,
            value=1,
        )
        skill = make_buff_skill("버프 스킬", "테스트 버프")
        ctx = make_context(buff, skill_dict={"버프 스킬": skill})
        manager = setup_enemy_pre_phase(ctx)

        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="버프 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/대상]")
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/버프 스킬/대상]")
        )
        target_id = CharacterId("대상")
        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert buffs[0].duration.remaining_count == 3

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert buffs[0].duration.remaining_count == 2

        ctx.on_finish_round()
        assert buffs[0].duration.remaining_count == 2

    def test_count_duration_buff_removed_after_expiry(self):
        buff = make_buff_data(
            "단기 버프",
            "BuffAtk",
            duration_turn_value=0,
            duration_count_value=1,
            duration_count_deduct_condition=BuffCountDeductCondition.ON_HIT,
            value_type=ValueType.INTEGER,
            value=1,
        )
        skill = make_buff_skill("버프 스킬", "단기 버프")
        ctx = make_context(buff, skill_dict={"버프 스킬": skill})
        manager = setup_enemy_pre_phase(ctx)

        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="버프 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/대상]")
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/버프 스킬/대상]")
        )
        target_id = CharacterId("대상")

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert len(buffs) == 0

    def test_count_duration_not_deducted_when_condition_not_met(self):
        """버프의 발동 조건이 충족되지 않았다면, 피격/공격이 있었더라도
        remaining_count가 소모되면 안 된다."""
        buff = make_buff_data(
            "테스트 버프",
            "BuffReceivedDamage",
            duration_turn_value=None,
            duration_count_value=3,
            duration_count_deduct_condition=BuffCountDeductCondition.ON_HIT,
            value_type=ValueType.INTEGER,
            value=-10,
            condition_="SelfHpBelowCondition",
            condition_value=30,
        )
        skill = make_buff_skill("버프 스킬", "테스트 버프")
        weak_attack = SkillData(
            id="약공격",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None)
            ],
            description="",
        )
        ctx = make_context(
            buff, skill_dict={"버프 스킬": skill, "약공격": weak_attack}
        )
        manager = setup_enemy_pre_phase(ctx)

        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="버프 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군", skill_1_id="약공격"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[스킬/약공격/대상]")
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬/버프 스킬/대상]")
        )
        target_id = CharacterId("대상")
        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert buffs[0].duration.remaining_count == 3

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        # 5 데미지만 받아 HP 비율(30%)을 밑돌지 않으므로 조건 미충족 → 대미지 감소도,
        # count 소모도 일어나지 않아야 한다.
        assert ctx.characters[target_id].status.curr_hp == 95
        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert buffs[0].duration.remaining_count == 3

    def test_passive_skill_wrapper_never_removed(self):
        from battle.objects.define import ValueSourceType
        from battle.objects.passive_skill.models import (
            PassiveSkillData,
            PassiveSkillTargetType,
            PassiveSkillTrigger,
        )
        from battle.objects.skill.effects import SkillEffectHeal

        passive = PassiveSkillData(
            id="패시브",
            trigger=PassiveSkillTrigger.ON_ACTION,
            target_type=PassiveSkillTargetType.SELF,
            effect=SkillEffectHeal(
                ValueSourceType.FIXED, 1, ValueType.INTEGER, None, None
            ),
            condition_class_name=None,
            condition_value=None,
            description="",
        )
        ctx = make_context(passive_skill_dict={"패시브": passive})
        ctx.add_character(
            get_test_preset("대상", passive_skill_id="패시브"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )

        for _ in range(5):
            ctx.on_finish_round()

        buffs = ctx.buff_container.get_buffs_by(CharacterId("대상"), None)
        assert any(b.id == "패시브" for b in buffs)


class TestPassiveSkillSelfHealOnGivenDamage:
    @pytest.fixture
    def ctx(self):
        from battle.objects.define import ValueSourceType
        from battle.objects.passive_skill.models import (
            PassiveSkillData,
            PassiveSkillTargetType,
            PassiveSkillTrigger,
        )
        from battle.objects.skill.effects import SkillEffectDamage, SkillEffectHeal

        lifesteal_passive = PassiveSkillData(
            id="생명력 흡수",
            trigger=PassiveSkillTrigger.ON_ACTION,
            target_type=PassiveSkillTargetType.SELF,
            effect=SkillEffectHeal(ValueSourceType.GIVEN_DAMAGE, 50, None, None, None),
            condition_class_name=None,
            condition_value=None,
            description="",
        )
        attack_skill = SkillData(
            id="고정 공격",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=1,
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
        return make_context(
            skill_dict={"고정 공격": attack_skill},
            passive_skill_dict={"생명력 흡수": lifesteal_passive},
        )

    def test_self_heal_after_attack(self, ctx):
        """고정 20 대미지 공격 후 50% = 10만큼 자신이 회복된다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset(
                "공격수",
                initial_hp=50,
                max_hp=100,
                skill_1_id="고정 공격",
                passive_skill_id="생명력 흡수",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=200),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        attacker_id = CharacterId("공격수")
        hp_before = ctx.characters[attacker_id].status.curr_hp

        manager.process_command(
            parse_character_command(attacker_id, "[스킬/고정 공격/적군]")
        )

        # 고정 20 대미지의 50% = 10 자기 회복
        assert ctx.characters[attacker_id].status.curr_hp == hp_before + 10


class TestPassiveSkillSelfHealOnGivenHeal:
    """ON_ACTION 패시브 스킬 + SkillEffectHeal(GIVEN_HEAL) + HealedNonSelfCondition: 공명 효과."""

    @pytest.fixture
    def ctx(self):
        from battle.objects.define import ValueSourceType
        from battle.objects.passive_skill.models import (
            PassiveSkillData,
            PassiveSkillTargetType,
            PassiveSkillTrigger,
        )
        from battle.objects.skill.effects import SkillEffectHeal

        resonance_passive = PassiveSkillData(
            id="공명",
            trigger=PassiveSkillTrigger.ON_ACTION,
            target_type=PassiveSkillTargetType.SELF,
            effect=SkillEffectHeal(ValueSourceType.GIVEN_HEAL, 50, None, None, None),
            condition_class_name="HealedNonSelfCondition",
            condition_value=None,
            description="",
        )
        heal_skill = SkillData(
            id="회복 스킬",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=1,
            effects=[
                SkillEffectHeal(
                    ValueSourceType.FIXED, 40, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
        return make_context(
            skill_dict={"회복 스킬": heal_skill},
            passive_skill_dict={"공명": resonance_passive},
        )

    def test_self_heal_triggers_when_healing_other(self, ctx):
        """공명 패시브 보유자가 타인을 회복하면 자신도 회복량의 50%를 회복한다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset(
                "힐러",
                initial_hp=50,
                max_hp=100,
                skill_1_id="회복 스킬",
                passive_skill_id="공명",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("환자", initial_hp=10, max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )

        healer_id = CharacterId("힐러")
        healer_hp_before = ctx.characters[healer_id].status.curr_hp

        manager.process_command(
            parse_character_command(healer_id, "[스킬/회복 스킬/환자]")
        )

        # 힐러 자신도 40 * 0.5 = 20 회복해야 한다
        assert ctx.characters[healer_id].status.curr_hp == healer_hp_before + 20

    def test_no_self_heal_when_healing_self(self, ctx):
        """공명 패시브 보유자가 자기 자신을 회복할 때는 추가 회복이 발생하지 않는다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset(
                "힐러",
                initial_hp=20,
                max_hp=100,
                skill_1_id="회복 스킬",
                passive_skill_id="공명",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )

        healer_id = CharacterId("힐러")

        manager.process_command(
            parse_character_command(healer_id, "[스킬/회복 스킬/힐러]")
        )

        # 자기 자신을 회복할 때는 추가 회복이 없으므로 정확히 40만 회복
        assert ctx.characters[healer_id].status.curr_hp == 60
