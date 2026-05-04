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
from battle.objects.buff.define import BuffDurationType
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffApplyTiming,
    ElementType,
    FactionType,
    MagicResistanceType,
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


def make_context(*buff_datas: BuffData, skill_dict: dict = None) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={b.id: b for b in buff_datas},
        skill_dict=skill_dict or {},
    )


def make_buff_data(
    buff_id: str,
    buff_class_name: str,
    *,
    duration_type: BuffDurationType = BuffDurationType.TURN,
    duration_value: int = 3,
    value_type: ValueType | None = None,
    value: int = 0,
    condition_: str | None = None,
    condition_value: int | None = None,
) -> BuffData:
    return BuffData(
        id=buff_id,
        buff_class_name=buff_class_name,
        duration_type=duration_type,
        duration_value=duration_value,
        value_type=value_type,
        value=value,
        condition_=condition_,
        condition_value=condition_value,
    )


def make_buff_skill(
    skill_id: str,
    buff_id: str,
    *,
    timing_if_enemy_skill: Optional[RoundPhaseType] = None,
) -> SkillData:
    return SkillData(
        skill_id,
        "SkillTargetRuleNamed",
        2,
        [
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=buff_id,
                buff_add_timing=timing_if_enemy_skill,
            )
        ],
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
            parse_character_command(CharacterId("버퍼"), "[스킬1/대상]")
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
            parse_character_command(CharacterId("버퍼"), "[스킬1/공격수]")
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
            parse_character_command(CharacterId("버퍼"), "[스킬1/공격수]")
        )
        ctx.characters[CharacterId("공격수")].status.remaining_cost = 3

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]")
        )
        hp_after_buff = ctx.characters[CharacterId("적군")].status.curr_hp
        damage_with_buff = hp_after_no_buff - hp_after_buff

        assert damage_with_buff > damage_no_buff


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

        # 적군 A에게 취약 버프 부여
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬1/적군 A]")
        )
        ctx.characters[CharacterId("공격수")].status.remaining_cost = 3

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 A]")
        )
        damage_to_buffed = 100 - ctx.characters[CharacterId("적군 A")].status.curr_hp

        ctx.characters[CharacterId("공격수")].status.remaining_cost = 3
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

        # 적군 A에게 방어 버프 부여
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬1/적군 A]")
        )
        ctx.characters[CharacterId("공격수")].status.remaining_cost = 3

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 A]")
        )
        damage_to_buffed = 100 - ctx.characters[CharacterId("적군 A")].status.curr_hp

        ctx.characters[CharacterId("공격수")].status.remaining_cost = 3
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
            parse_character_command(CharacterId("버퍼"), "[스킬1/적군]")
        )
        ctx.characters[CharacterId("공격수")].status.remaining_cost = 3
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
        heal_skill = SkillData(
            "회복 스킬",
            "SkillTargetRuleNamed",
            2,
            [SkillEffectHeal(None, 30, None, None, None)],
        )
        debuff_skill = make_buff_skill("회복 불가 스킬", "회복 불가")
        from battle.objects.define import ValueSourceType

        heal_skill2 = SkillData(
            "회복 스킬",
            "SkillTargetRuleNamed",
            2,
            [SkillEffectHeal(ValueSourceType.FIXED, 30, ValueType.INTEGER, None, None)],
        )
        return make_context(
            debuff,
            skill_dict={"회복 불가 스킬": debuff_skill, "회복 스킬": heal_skill2},
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
            parse_character_command(CharacterId("디버퍼"), "[스킬1/환자]")
        )
        ctx.characters[CharacterId("힐러")].status.remaining_cost = 3
        initial_hp = ctx.characters[CharacterId("환자")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("힐러"), "[스킬2/환자]")
        )

        assert ctx.characters[CharacterId("환자")].status.curr_hp == initial_hp


class TestBuffDamageOverTime:
    """BuffDamageOverTime: 라운드 종료 시 고정 대미지를 입힌다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data(
            "독",
            "BuffDamageOverTime",
            duration_type=BuffDurationType.TURN,
            duration_value=2,
            value=10,
        )
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
            parse_character_command(CharacterId("독사"), "[스킬1/아군]")
        )
        initial_hp = ctx.characters[CharacterId("아군")].status.curr_hp

        # 라운드 종료 처리 (on_finish_round 내에서 buff_container.on_round_end 호출됨)
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
            parse_character_command(CharacterId("독사"), "[스킬1/아군]")
        )

        # 2턴 경과
        ctx.on_finish_round()
        ctx.on_finish_round()

        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ROUND_END)
        assert len(buffs) == 0


# ─── BuffHealOverTime (도트 회복) ─────────────────────────────────────────────


class TestBuffHealOverTime:
    """BuffHealOverTime: 라운드 종료 시 고정 회복량을 회복한다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data(
            "재생",
            "BuffHealOverTime",
            duration_type=BuffDurationType.TURN,
            duration_value=2,
            value=20,
        )
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
            parse_character_command(CharacterId("힐러"), "[스킬1/환자]")
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
            parse_character_command(CharacterId("힐러"), "[스킬1/환자]")
        )
        ctx.on_finish_round()

        assert ctx.characters[target_id].status.curr_hp <= 100


# ─── BuffTaunt (도발) ─────────────────────────────────────────────────────────


class TestBuffTaunt:
    """BuffTaunt: 공격 시 공격 대상을 도발자로 강제 변경한다."""

    @pytest.fixture
    def ctx(self):
        buff = make_buff_data("도발", "BuffTaunt")
        skill = make_buff_skill("도발 스킬", "도발")
        return make_context(buff, skill_dict={"도발 스킬": skill})

    def test_taunt_redirects_attack(self, ctx):
        """도발 버프를 받은 캐릭터를 공격하면, 실제 대미지는 도발자에게 들어간다."""
        manager = setup_ally_phase(ctx)
        # 아군 버퍼가 도발 버프를 적군 A에게 부여한다. 도발 버프의 taunter는 버프 부여자.
        # 아군이 적군 B를 공격하면, 도발 버프로 인해 실제 대미지는 버프 부여자(버퍼)에게 들어간다.
        # → 여기서는 적군이 적군에게 도발을 거는 시나리오: 적군 A(도발자)가 아군에게 도발을 걺
        # 구현 편의상 아군이 아군에게 도발 걸고, 다른 아군이 공격하는 케이스로 테스트

        ctx.add_character(
            get_test_preset("도발자", skill_1_id="도발 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("미끼", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("진짜 대상", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )

        # 미끼에게 도발 부여 → 실제 대미지는 도발자(도발 스킬 사용자)에게 가야 한다
        # BuffTaunt의 taunter = given_by = 도발자
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[스킬1/미끼]")
        )
        ctx.characters[CharacterId("공격수")].status.remaining_cost = 3

        hp_decoy_before = ctx.characters[CharacterId("미끼")].status.curr_hp
        hp_taunt_before = ctx.characters[CharacterId("진짜 대상")].status.curr_hp

        # 공격수가 미끼를 공격 → 도발에 의해 진짜 대상(도발자=버프 부여자)에게 대미지가 가야 함
        # 현 구조상 taunter == given_by == 도발자(아군), 적군은 아군을 공격 대상으로 지정 불가
        # → 도발 버프의 실제 동작: attacker가 holder를 공격할 때 target을 taunter로 바꿈
        # 즉 공격수가 미끼를 공격하면 → 실제로는 도발자(아군)에게 대미지가 감
        # 아군 HP 감소 확인으로 테스트
        taunt_holder_id = CharacterId("도발자")
        hp_before = ctx.characters[taunt_holder_id].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/미끼]")
        )

        # 미끼는 피해를 받지 않고, 도발자가 피해를 받아야 한다
        assert ctx.characters[CharacterId("미끼")].status.curr_hp == hp_decoy_before
        assert ctx.characters[taunt_holder_id].status.curr_hp < hp_before


# ─── 버프 지속 시간 공통 ──────────────────────────────────────────────────────


class TestBuffDuration:
    """버프 지속 시간(TURN/COUNT) 공통 동작 테스트."""

    def test_turn_duration_decrements_on_round_end(self):
        """TURN 타입 버프는 라운드 종료마다 남은 턴수가 차감된다."""
        buff = make_buff_data(
            "테스트 버프",
            "BuffAtk",
            duration_type=BuffDurationType.TURN,
            duration_value=3,
            value_type=ValueType.INTEGER,
            value=1,
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
            parse_character_command(CharacterId("버퍼"), "[스킬1/대상]")
        )
        target_id = CharacterId("대상")

        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert buffs[0].duration.remaining_turns == 3

        ctx.on_finish_round()
        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ACTION)
        assert buffs[0].duration.remaining_turns == 2

    def test_turn_duration_buff_removed_after_expiry(self):
        """TURN 타입 버프는 지속 턴수가 0이 되면 제거된다."""
        buff = make_buff_data(
            "단기 버프",
            "BuffAtk",
            duration_type=BuffDurationType.TURN,
            duration_value=1,
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
            parse_character_command(CharacterId("버퍼"), "[스킬1/대상]")
        )

        ctx.on_finish_round()

        buffs = ctx.buff_container.get_buffs_by(
            CharacterId("대상"), BuffApplyTiming.ON_ACTION
        )
        assert len(buffs) == 0

    def test_passive_buff_never_removed(self):
        """PASSIVE 타입 버프는 라운드가 종료되어도 제거되지 않는다."""
        buff = make_buff_data(
            "패시브 버프",
            "BuffAtk",
            duration_type=BuffDurationType.PASSIVE,
            duration_value=0,
            value_type=ValueType.INTEGER,
            value=1,
        )
        skill = make_buff_skill("패시브 스킬", "패시브 버프")
        ctx = make_context(buff, skill_dict={"패시브 스킬": skill})
        manager = setup_ally_phase(ctx)

        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="패시브 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[스킬1/대상]")
        )

        # 여러 라운드 종료
        for _ in range(5):
            ctx.on_finish_round()

        buffs = ctx.buff_container.get_buffs_by(
            CharacterId("대상"), BuffApplyTiming.ON_ACTION
        )
        assert len(buffs) > 0
