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
            parse_character_command(CharacterId("버퍼"), "[버프 스킬/대상]", ctx)
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

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]", ctx)
        )
        hp_after_no_buff = ctx.characters[CharacterId("적군")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[버프 스킬/공격수]", ctx)
        )
        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]", ctx)
        )
        hp_after_buff = ctx.characters[CharacterId("적군")].status.curr_hp

        damage_no_buff = 100 - hp_after_no_buff
        damage_with_buff = hp_after_no_buff - hp_after_buff
        assert damage_with_buff > damage_no_buff

    def test_atk_buff_reflected_in_bonus_damage_on_hit(self):
        """BuffBonusDamageOnHit는 STAT_ATK를 참조하므로, 공격자의 BuffAtk가
        반영된 값으로 추가 대미지가 계산되어야 한다."""
        atk_buff = make_buff_data(
            "공격력 증가", "BuffAtk", value_type=ValueType.INTEGER, value=50
        )
        retaliate_buff = make_buff_data(
            "반격",
            "BuffBonusDamageOnHit",
            duration_turn_value=None,
            value_type=ValueType.INTEGER,
            value=20,  # 계수 20% → 보너스 대미지 = ATK × 0.2
        )
        atk_buff_skill = make_buff_skill("버프 스킬", "공격력 증가")
        weak_attack = SkillData(
            id="약공격",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
        ctx = make_context(
            atk_buff,
            retaliate_buff,
            skill_dict={"버프 스킬": atk_buff_skill, "약공격": weak_attack},
        )
        manager = setup_ally_phase(ctx)

        attacker_id = CharacterId("공격수")
        target_id = CharacterId("대상")
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="버프 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수", atk=5, skill_1_id="약공격"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        ctx.buff_container.add(
            BuffAddData(given_by=target_id, applied_to=target_id, buff_id="반격")
        )

        # ATK 버프 없이 공격 (ATK=5 → 보너스 대미지 floor(5*0.2)=1, 고정 5 + 1 = 6)
        manager.process_command(
            parse_character_command(attacker_id, "[약공격/대상]", ctx)
        )
        hp_after_no_buff = ctx.characters[target_id].status.curr_hp
        assert hp_after_no_buff == 94

        # 대상 원상 복구 후, 공격수에게 ATK 버프 부여
        # → ATK 55 → 보너스 대미지 floor(55*0.2)=11, 고정 5 + 11 = 16
        ctx.characters[target_id].status.curr_hp = 100
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[버프 스킬/공격수]", ctx)
        )
        manager.process_command(
            parse_character_command(attacker_id, "[약공격/대상]", ctx)
        )
        hp_after_buff = ctx.characters[target_id].status.curr_hp
        assert hp_after_buff == 84


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
            # ATK를 키워 +50% 버프(×1.5)가 1d6 변동을 항상 압도하도록 한다.
            # (최소 버프딜 floor(21*1.5)=31 > 최대 무버프딜 26, 최대딜 39 < 100HP로 비살상)
            get_test_preset("공격수", atk=20),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]", ctx)
        )
        hp_after_no_buff = ctx.characters[CharacterId("적군")].status.curr_hp
        damage_no_buff = 100 - hp_after_no_buff

        manager.process_command(
            parse_character_command(
                CharacterId("버퍼"), "[대미지 증가 스킬/공격수]", ctx
            )
        )

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]", ctx)
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
        # FIXED 값은 BuffGivenDamage(버프)에 면역이므로, 이 테스트는 ATK 기반
        # 계수 100%(=ATK 그대로)로 5 대미지를 낸다 (FIXED 5와 동일한 기본
        # 대미지를 내면서도 버프가 실제로 적용되는 경로를 검증한다).
        aoe_skill = SkillData(
            id="광역기",
            target_rule="SkillTargetRuleColumn",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    ValueSourceType.STAT_ATK, 100, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
        ctx = make_context(buff, skill_dict={"광역기": aoe_skill})
        manager = setup_ally_phase(ctx)

        attacker_id = CharacterId("공격수")
        ctx.add_character(
            get_test_preset("공격수", skill_1_id="광역기", atk=5),
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
            parse_character_command(attacker_id, "[광역기/1열]", ctx)
        )

        # 고정 5 대미지 + 버프 고정 +10 = 15. 대상 수만큼 중복 적용되면 25가 된다.
        assert ctx.characters[CharacterId("적군1")].status.curr_hp == 100 - 15
        assert ctx.characters[CharacterId("적군2")].status.curr_hp == 100 - 15

        buffs = ctx.buff_container.get_buffs_by(attacker_id, BuffApplyTiming.ON_ACTION)
        assert len(buffs) == 1
        # 대상이 둘이어도 행동은 1회이므로 count는 1만 소모되어야 한다.
        assert buffs[0].duration.remaining_count == 2

    def test_count_buff_not_double_deducted_by_multi_effect_skill_on_same_target(self):
        """스킬 하나가 effect 두 개로 같은 대상에게 대미지를 나누어 입혀도, 공격자
        측(ON_ATTACK)과 대상 측(ON_HIT) count형 버프는 행동 1회당 한 번만
        차감되어야 한다 — 두 effect를 두 번의 순차적 타격으로 취급하면 안 된다."""
        attack_buff = make_buff_data(
            "대미지 증가",
            "BuffGivenDamage",
            duration_turn_value=None,
            duration_count_value=3,
            duration_count_deduct_condition=BuffCountDeductCondition.ON_ATTACK,
            value_type=ValueType.INTEGER,
            value=10,
        )
        hit_buff = make_buff_data(
            "피해 증가",
            "BuffReceivedDamage",
            duration_turn_value=None,
            duration_count_value=3,
            duration_count_deduct_condition=BuffCountDeductCondition.ON_HIT,
            value_type=ValueType.PERCENT,
            value=10,
        )
        two_effect_skill = SkillData(
            id="이단 타격",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None
                ),
                SkillEffectDamage(
                    ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None
                ),
            ],
            description="",
        )
        ctx = make_context(
            attack_buff, hit_buff, skill_dict={"이단 타격": two_effect_skill}
        )
        manager = setup_ally_phase(ctx)

        attacker_id = CharacterId("공격수")
        target_id = CharacterId("적군")
        ctx.add_character(
            get_test_preset("공격수", skill_1_id="이단 타격"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        ctx.buff_container.add(
            BuffAddData(
                given_by=attacker_id, applied_to=attacker_id, buff_id="대미지 증가"
            )
        )
        ctx.buff_container.add(
            BuffAddData(given_by=target_id, applied_to=target_id, buff_id="피해 증가")
        )

        manager.process_command(
            parse_character_command(attacker_id, "[이단 타격/적군]", ctx)
        )

        attack_buffs = ctx.buff_container.get_buffs_by(
            attacker_id, BuffApplyTiming.ON_ACTION
        )
        hit_buffs = ctx.buff_container.get_buffs_by(
            target_id, BuffApplyTiming.ON_ACTION
        )
        # effect가 둘이어도 실제 타격은 1회이므로 양쪽 다 count는 1만 소모되어야 한다.
        assert attack_buffs[0].duration.remaining_count == 2
        assert hit_buffs[0].duration.remaining_count == 2


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

    def test_received_damage_buff_increases_damage_taken(
        self, ctx_damage_up, monkeypatch
    ):
        """받는 대미지 증가 버프를 받은 캐릭터는 더 큰 피해를 입는다.

        두 공격이 각자 독립적으로 1d6을 굴리면, +50% 버프로도 주사위 눈 차이를
        항상 뒤집을 수는 없어(예: 버프 쪽이 낮은 눈, 비버프 쪽이 높은 눈이 나오면
        역전) 드물게 실패하는 flaky 테스트였다. 두 공격이 같은 주사위 눈을
        굴리도록 고정해 버프 효과 자체만 결정론적으로 검증한다.
        """
        monkeypatch.setattr("random.randint", lambda a, b: 4)
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
            parse_character_command(CharacterId("버퍼"), "[취약 스킬/적군 A]", ctx)
        )

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 A]", ctx)
        )
        damage_to_buffed = 100 - ctx.characters[CharacterId("적군 A")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 B]", ctx)
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
            parse_character_command(CharacterId("버퍼"), "[방어 스킬/적군 A]", ctx)
        )

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 A]", ctx)
        )
        damage_to_buffed = 100 - ctx.characters[CharacterId("적군 A")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군 B]", ctx)
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

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[무적 스킬/적군]", ctx)
        )

        initial_hp = ctx.characters[CharacterId("적군")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[공격/적군]", ctx)
        )

        assert ctx.characters[CharacterId("적군")].status.curr_hp == initial_hp


class TestBuffGuardReflect:
    """BuffGuardReflect: 물리 대미지 80% 경감 + 마법 대미지 무효화 +
    경감 전 원래 대미지 50% 반사(물리/마법 공통). 도트 등 FIXED 값 파생
    대미지에도 경감이 적용되고, 같은 스킬이 함께 부여하는 부가 효과(버프)는
    대미지 경감과 무관하게 그대로 적용되어야 한다."""

    @pytest.fixture
    def ctx(self):
        guard_buff = make_buff_data(
            "수호",
            "BuffGuardReflect",
            duration_turn_value=None,
            value_type=ValueType.PERCENT,
            value=50,
        )
        guard_skill = make_buff_skill("수호 스킬", "수호")
        fixed_damage_skill = SkillData(
            id="고정 대미지 스킬",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=100,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
                )
            ],
            description="",
        )
        marker_buff = make_buff_data(
            "표식", "BuffReceivedDamage", value_type=ValueType.PERCENT, value=0
        )
        dot_buff = make_buff_data("독", "BuffDamageOverTime", value=50)
        combined_skill = SkillData(
            id="복합 스킬",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=100,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
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
        return make_context(
            guard_buff,
            marker_buff,
            dot_buff,
            skill_dict={
                "수호 스킬": guard_skill,
                "고정 대미지 스킬": fixed_damage_skill,
                "복합 스킬": combined_skill,
            },
        )

    def test_physical_damage_reduced_by_80_percent_and_reflects_half_of_original(
        self, ctx
    ):
        """물리 공격자는 100의 20%(부동소수점 오차로 19)만 대미지를 입히지만,
        반사량은 경감 전 원래 대미지(100) 기준 50%인 50이다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="수호 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수", skill_1_id="고정 대미지 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[수호 스킬/적군]", ctx)
        )
        attacker_hp_before = ctx.characters[CharacterId("공격수")].status.curr_hp

        manager.process_command(
            parse_character_command(
                CharacterId("공격수"), "[고정 대미지 스킬/적군]", ctx
            )
        )

        assert ctx.characters[CharacterId("적군")].status.curr_hp == 100 - 19
        assert (
            attacker_hp_before - ctx.characters[CharacterId("공격수")].status.curr_hp
            == 50
        )

    def test_magic_damage_fully_nullified_but_still_reflects_half_of_original(
        self, ctx
    ):
        """마법 공격은 완전히 무효화되어 대상 HP가 그대로지만, 반사량은
        경감(무효화) 전 원래 대미지(100) 기준 50%인 50이라 공격자는 그만큼
        피해를 입는다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="수호 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset(
                "마법공격수", is_magic_attacker=True, skill_1_id="고정 대미지 스킬"
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[수호 스킬/적군]", ctx)
        )
        attacker_hp_before = ctx.characters[CharacterId("마법공격수")].status.curr_hp

        manager.process_command(
            parse_character_command(
                CharacterId("마법공격수"), "[고정 대미지 스킬/적군]", ctx
            )
        )

        assert ctx.characters[CharacterId("적군")].status.curr_hp == 100
        assert (
            attacker_hp_before
            - ctx.characters[CharacterId("마법공격수")].status.curr_hp
            == 50
        )

    def test_dot_damage_is_also_reduced(self, ctx):
        """도트(고정값) 대미지도 물리 공격과 동일하게 80% 경감된다."""
        ctx.add_character(
            get_test_preset("독사"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=CharacterId("대상"),
                applied_to=CharacterId("대상"),
                buff_id="수호",
            )
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=CharacterId("독사"),
                applied_to=CharacterId("대상"),
                buff_id="독",
            )
        )
        initial_hp = ctx.characters[CharacterId("대상")].status.curr_hp

        ctx.on_finish_round()

        # 독 50 고정 대미지 × (1 - 80%) = 부동소수점 오차로 9.
        assert initial_hp - ctx.characters[CharacterId("대상")].status.curr_hp == 9

    def test_attached_debuff_still_applies_despite_physical_reduction(self, ctx):
        """같은 스킬이 함께 부여하는 부가 효과(디버프)는 대미지 경감과
        무관하게 정상적으로 적용된다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="수호 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수", skill_1_id="복합 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[수호 스킬/적군]", ctx)
        )
        manager.process_command(
            parse_character_command(CharacterId("공격수"), "[복합 스킬/적군]", ctx)
        )

        assert ctx.characters[CharacterId("적군")].status.curr_hp == 100 - 19
        assert any(
            b.id == "표식"
            for b in ctx.buff_container.get_buffs_by(CharacterId("적군"), None)
        )

    def test_attached_debuff_still_applies_despite_magic_nullification(self, ctx):
        """마법 공격으로 대미지가 완전히 무효화되어도 함께 부여되는 부가
        효과(디버프)는 그대로 적용된다."""
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="수호 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset(
                "마법공격수", is_magic_attacker=True, skill_1_id="복합 스킬"
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[수호 스킬/적군]", ctx)
        )
        manager.process_command(
            parse_character_command(CharacterId("마법공격수"), "[복합 스킬/적군]", ctx)
        )

        assert ctx.characters[CharacterId("적군")].status.curr_hp == 100
        assert any(
            b.id == "표식"
            for b in ctx.buff_container.get_buffs_by(CharacterId("적군"), None)
        )

    def test_reflect_percent_is_configurable_via_value(self):
        """반사 배율은 하드코딩이 아니라 버프의 value(퍼센트)를 그대로 쓴다 —
        50% 대신 30%로 등록하면 반사량도 그에 맞게 원래 대미지의 30%가
        된다."""
        buff = make_buff_data(
            "수호_30",
            "BuffGuardReflect",
            duration_turn_value=None,
            value_type=ValueType.PERCENT,
            value=30,
        )
        skill = make_buff_skill("수호_30 스킬", "수호_30")
        fixed_damage_skill = SkillData(
            id="고정 대미지 스킬_30",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=100,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
                )
            ],
            description="",
        )
        ctx = make_context(
            buff,
            skill_dict={
                "수호_30 스킬": skill,
                "고정 대미지 스킬_30": fixed_damage_skill,
            },
        )
        manager = setup_ally_phase(ctx)
        ctx.add_character(
            get_test_preset("버퍼", skill_1_id="수호_30 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수", skill_1_id="고정 대미지 스킬_30"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[수호_30 스킬/적군]", ctx)
        )
        attacker_hp_before = ctx.characters[CharacterId("공격수")].status.curr_hp
        manager.process_command(
            parse_character_command(
                CharacterId("공격수"), "[고정 대미지 스킬_30/적군]", ctx
            )
        )

        # 경감 전 원래 대미지(100)의 30% = 30이 반사된다(50%였다면 50).
        assert (
            attacker_hp_before - ctx.characters[CharacterId("공격수")].status.curr_hp
            == 30
        )

    def test_non_percent_value_type_is_rejected(self):
        """value_type이 퍼센트가 아니면 잘못된 배율로 조용히 계산하는 대신
        명시적으로 에러를 발생시켜야 한다."""
        buff = make_buff_data(
            "수호_정수",
            "BuffGuardReflect",
            duration_turn_value=None,
            value_type=ValueType.INTEGER,
            value=50,
        )
        ctx = make_context(buff)
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=CharacterId("대상"),
                applied_to=CharacterId("대상"),
                buff_id="수호_정수",
            )
        )

        buff_instance = ctx.buff_container.get_buffs_by(
            CharacterId("대상"), BuffApplyTiming.ON_ACTION
        )[0]
        with pytest.raises(ValueError):
            buff_instance.create_event()


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

        manager.process_command(
            parse_character_command(CharacterId("디버퍼"), "[회복 불가 스킬/환자]", ctx)
        )
        initial_hp = ctx.characters[CharacterId("환자")].status.curr_hp

        manager.process_command(
            parse_character_command(CharacterId("힐러"), "[회복 스킬/환자]", ctx)
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
            parse_character_command(CharacterId("독사"), "[독 스킬/아군]", ctx)
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
            parse_character_command(CharacterId("독사"), "[독 스킬/아군]", ctx)
        )

        for i in range(3):
            ctx.on_finish_round()

        buffs = ctx.buff_container.get_buffs_by(target_id, BuffApplyTiming.ON_ROUND_END)
        assert len(buffs) == 0

    def test_dot_rejects_percent_value_type(self):
        """value_type=PERCENT는 '고정 대미지'라는 버프 취지와 맞지 않으므로
        조용히 정수로 취급되지 않고 명시적으로 에러를 발생시켜야 한다."""
        buff = make_buff_data(
            "독", "BuffDamageOverTime", value=10, value_type=ValueType.PERCENT
        )
        ctx = make_context(buff)
        ctx.add_character(
            get_test_preset("대상"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=CharacterId("대상"),
                applied_to=CharacterId("대상"),
                buff_id="독",
            )
        )

        with pytest.raises(ValueError):
            ctx.on_finish_round()


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
            parse_character_command(CharacterId("힐러"), "[재생 스킬/환자]", ctx)
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
            parse_character_command(CharacterId("힐러"), "[재생 스킬/환자]", ctx)
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

    def test_taunt_redirects_attack(self, ctx, monkeypatch):
        """도발 버프를 받은 캐릭터를 공격하면, 실제 대미지는 도발자에게 들어간다."""
        # 선언된 공격 인스턴스가 1개뿐이라 추첨은 사실상 확정적이지만,
        # random.choice의 내부 동작에 우연히 의존하지 않도록 고정한다.
        monkeypatch.setattr("random.choice", lambda seq: seq[0])
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
            parse_character_command(CharacterId("적군"), "[공격/공격수]", ctx)
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[도발 스킬/적군]", ctx)
        )

        taunted_buff = ctx.buff_container.get_buffs_by(CharacterId("적군"), None)[0]
        assert taunted_buff.display_id_label() == "도발: 도발자"

        hp_dealer_before = ctx.characters[CharacterId("공격수")].status.curr_hp
        hp_taunter_before = ctx.characters[CharacterId("도발자")].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.characters[CharacterId("공격수")].status.curr_hp == hp_dealer_before
        assert ctx.characters[CharacterId("도발자")].status.curr_hp < hp_taunter_before

    def test_taunt_redirects_skill_damage_and_attached_debuff(self, monkeypatch):
        """도발받은 적이 대미지+디버프 스킬을 쓰면, 대미지뿐 아니라 딸린 디버프도
        도발자에게 함께 적용되어야 한다."""
        monkeypatch.setattr("random.choice", lambda seq: seq[0])
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
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군", skill_1_id="저주 일격"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[저주 일격/공격수]", ctx)
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[도발 스킬/적군]", ctx)
        )

        hp_dealer_before = ctx.characters[CharacterId("공격수")].status.curr_hp
        hp_taunter_before = ctx.characters[CharacterId("도발자")].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.characters[CharacterId("공격수")].status.curr_hp == hp_dealer_before
        assert ctx.characters[CharacterId("도발자")].status.curr_hp < hp_taunter_before

        dealer_buffs = ctx.buff_container.get_buffs_by(
            CharacterId("공격수"), BuffApplyTiming.ON_ACTION
        )
        taunter_buffs = ctx.buff_container.get_buffs_by(
            CharacterId("도발자"), BuffApplyTiming.ON_ACTION
        )
        assert not any(b.id == "디버프" for b in dealer_buffs)
        assert any(b.id == "디버프" for b in taunter_buffs)

    def test_taunt_does_not_redirect_column_aoe_damage(self, monkeypatch):
        """열 광역 스킬(SkillTargetRuleColumn)은 시전자가 도발 상태여도
        대미지가 도발자에게 몰리지 않고, 열에 있는 각 대상이 그대로 맞아야
        한다 — 대상별로 이동/피격을 개별 판단해야 하는 설계이기 때문."""
        monkeypatch.setattr("random.choice", lambda seq: seq[0])
        taunt_buff = make_buff_data("도발", "BuffTaunt")
        taunt_skill = make_buff_skill("도발 스킬", "도발")
        aoe_skill = SkillData(
            id="열 공격",
            target_rule="SkillTargetRuleColumn",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=10,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
                )
            ],
            description="",
        )
        ctx = make_context(
            taunt_buff, skill_dict={"도발 스킬": taunt_skill, "열 공격": aoe_skill}
        )
        manager = setup_enemy_pre_phase(ctx)

        # 도발자는 열 공격의 대상 열(0열)과 다른 열에 있어야 한다 — 도발이
        # 리다이렉트를 일으키지 않는지 검증하려는 것이지, 도발자가 원래부터
        # 그 열에 있어서 맞는 것과 구분해야 하기 때문이다.
        ctx.add_character(
            get_test_preset("도발자", skill_1_id="도발 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(3),
        )
        ctx.add_character(
            get_test_preset("공격수1"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("공격수2"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군", skill_1_id="열 공격"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[열 공격/1열]", ctx)
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[도발 스킬/적군]", ctx)
        )

        hp_taunter_before = ctx.characters[CharacterId("도발자")].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.characters[CharacterId("도발자")].status.curr_hp == hp_taunter_before
        assert ctx.characters[CharacterId("공격수1")].status.curr_hp == 100 - 10
        assert ctx.characters[CharacterId("공격수2")].status.curr_hp == 100 - 10

    def test_taunt_redirects_only_one_of_two_declared_same_target_attacks(
        self, ctx, monkeypatch
    ):
        """같은 대상을 노리는 공격을 두 번 선언해도([공격/B - 공격/B]),
        도발로 리다이렉트되는 건 그중 하나뿐이다 — 나머지 하나는 원래 대상에게
        그대로 들어간다. 두 공격 모두 같은 눈의 주사위를 굴리도록 고정해,
        피해량으로 '몇 번 맞았는지'를 결정론적으로 셀 수 있게 한다."""
        monkeypatch.setattr("random.randint", lambda a, b: 4)
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
            get_test_preset("기준공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(1)
        )
        ctx.add_character(
            get_test_preset("적군_기준"), FactionType.ENEMY, BattlefieldColumnIndex(1)
        )

        manager.process_command(
            parse_character_command(
                CharacterId("적군"), "[공격/공격수 - 공격/공격수]", ctx
            )
        )
        # 도발과 무관한 단독 공격 1회 — 공격 한 번당 피해량(single_hit_damage)의
        # 기준값을 얻기 위한 대조군.
        manager.process_command(
            parse_character_command(CharacterId("적군_기준"), "[공격/기준공격수]", ctx)
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[도발 스킬/적군]", ctx)
        )

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        single_hit_damage = (
            100 - ctx.characters[CharacterId("기준공격수")].status.curr_hp
        )
        assert single_hit_damage > 0
        assert (
            100 - ctx.characters[CharacterId("공격수")].status.curr_hp
            == single_hit_damage
        )
        assert (
            100 - ctx.characters[CharacterId("도발자")].status.curr_hp
            == single_hit_damage
        )

    def test_taunt_leaves_taunter_targeting_instance_and_redirects_the_rest(self):
        """이미 도발자를 대상에 포함한 다중 타겟 스킬([스킬/도발자/공격수])을
        선언하면, 도발자를 향한 인스턴스는 그대로 두고 나머지(공격수)만
        도발자에게 redirect된다."""
        taunt_buff = make_buff_data("도발", "BuffTaunt")
        taunt_skill = make_buff_skill("도발 스킬", "도발")
        double_hit_skill = SkillData(
            id="양손 가르기",
            target_rule="SkillTargetRuleNamed",
            target_count=2,
            cost=2,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=10,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
                )
            ],
            description="",
        )
        ctx = make_context(
            taunt_buff,
            skill_dict={"도발 스킬": taunt_skill, "양손 가르기": double_hit_skill},
        )
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
            get_test_preset("적군", skill_1_id="양손 가르기"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )

        manager.process_command(
            parse_character_command(
                CharacterId("적군"), "[양손 가르기/도발자/공격수]", ctx
            )
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[도발 스킬/적군]", ctx)
        )

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        # 도발자를 이미 노린 인스턴스는 그대로, 공격수를 노린 인스턴스도 함께
        # 도발자에게 redirect되어 도발자는 두 번(20), 공격수는 0 피해.
        assert ctx.characters[CharacterId("도발자")].status.curr_hp == 100 - 20
        assert ctx.characters[CharacterId("공격수")].status.curr_hp == 100

    def test_taunt_redirects_one_of_two_different_targets_in_multi_target_skill(
        self, monkeypatch
    ):
        """도발자가 아닌 서로 다른 두 대상을 지정한 다중 타겟 스킬
        ([스킬/공격수1/공격수2])은 둘 중 하나만 무작위로 도발자에게
        redirect되고, 나머지 하나는 원래 대상 그대로 맞는다."""
        monkeypatch.setattr("random.choice", lambda seq: seq[0])
        taunt_buff = make_buff_data("도발", "BuffTaunt")
        taunt_skill = make_buff_skill("도발 스킬", "도발")
        double_hit_skill = SkillData(
            id="양손 가르기",
            target_rule="SkillTargetRuleNamed",
            target_count=2,
            cost=2,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=10,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
                )
            ],
            description="",
        )
        ctx = make_context(
            taunt_buff,
            skill_dict={"도발 스킬": taunt_skill, "양손 가르기": double_hit_skill},
        )
        manager = setup_enemy_pre_phase(ctx)

        ctx.add_character(
            get_test_preset("도발자", skill_1_id="도발 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수1"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("공격수2"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군", skill_1_id="양손 가르기"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )

        manager.process_command(
            parse_character_command(
                CharacterId("적군"), "[양손 가르기/공격수1/공격수2]", ctx
            )
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자"), "[도발 스킬/적군]", ctx)
        )

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        # random.choice를 seq[0](선언 순서상 첫 대상인 공격수1의 인스턴스)로
        # 고정했으므로 공격수1만 도발자에게 redirect되고 공격수2는 그대로 맞는다.
        assert ctx.characters[CharacterId("공격수1")].status.curr_hp == 100
        assert ctx.characters[CharacterId("공격수2")].status.curr_hp == 100 - 10
        assert ctx.characters[CharacterId("도발자")].status.curr_hp == 100 - 10

    def test_two_simultaneous_taunters_each_claim_one_declared_attack(self, ctx):
        """도발자 두 명에게 동시에 도발당한 적이 서로 다른 대상 둘에게 공격을
        하나씩 선언하면([공격/공격수1 - 공격/공격수2]), 원래 대상은 전혀
        맞지 않고 두 도발자가 각각 하나씩 맞는다. 풀 크기와 도발자 수가
        같아(2:2) 어느 쪽이 어느 인스턴스를 뽑든 결과가 대칭이므로, 이
        검증은 random.choice를 고정하지 않아도 결정론적이다."""
        manager = setup_enemy_pre_phase(ctx)

        ctx.add_character(
            get_test_preset("도발자1", skill_1_id="도발 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("도발자2", skill_1_id="도발 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수1"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("공격수2"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )

        manager.process_command(
            parse_character_command(
                CharacterId("적군"), "[공격/공격수1 - 공격/공격수2]", ctx
            )
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자1"), "[도발 스킬/적군]", ctx)
        )
        manager.process_command(
            parse_character_command(CharacterId("도발자2"), "[도발 스킬/적군]", ctx)
        )

        hp1_before = ctx.characters[CharacterId("공격수1")].status.curr_hp
        hp2_before = ctx.characters[CharacterId("공격수2")].status.curr_hp
        taunter1_hp_before = ctx.characters[CharacterId("도발자1")].status.curr_hp
        taunter2_hp_before = ctx.characters[CharacterId("도발자2")].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.characters[CharacterId("공격수1")].status.curr_hp == hp1_before
        assert ctx.characters[CharacterId("공격수2")].status.curr_hp == hp2_before
        assert (
            ctx.characters[CharacterId("도발자1")].status.curr_hp < taunter1_hp_before
        )
        assert (
            ctx.characters[CharacterId("도발자2")].status.curr_hp < taunter2_hp_before
        )

    def test_taunt_locks_instances_already_targeting_a_taunter(self, ctx, monkeypatch):
        """이미 어떤 도발자를 직접 겨냥한 인스턴스는 다른 도발자에게
        가로채이지 않고 그대로 유지된다 — 겹치지 않는 나머지 인스턴스만
        재추첨 대상이 된다. 도발자1이 이름순으로 먼저 처리되므로, 유일하게
        남은 풀(공격수 인스턴스)은 도발자1에게 돌아간다."""
        monkeypatch.setattr("random.randint", lambda a, b: 4)
        manager = setup_enemy_pre_phase(ctx)

        ctx.add_character(
            get_test_preset("도발자1", skill_1_id="도발 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("도발자2", skill_1_id="도발 스킬"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("공격수"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("기준공격수"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )
        ctx.add_character(
            get_test_preset("적군_기준"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )

        manager.process_command(
            parse_character_command(
                CharacterId("적군"),
                "[공격/도발자1 - 공격/도발자2 - 공격/공격수]",
                ctx,
            )
        )
        manager.process_command(
            parse_character_command(CharacterId("적군_기준"), "[공격/기준공격수]", ctx)
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("도발자1"), "[도발 스킬/적군]", ctx)
        )
        manager.process_command(
            parse_character_command(CharacterId("도발자2"), "[도발 스킬/적군]", ctx)
        )

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        single_hit_damage = (
            100 - ctx.characters[CharacterId("기준공격수")].status.curr_hp
        )
        assert single_hit_damage > 0

        # 공격수를 향한 인스턴스는 도발자1에게 재배정되어 공격수는 전혀 안 맞는다.
        assert ctx.characters[CharacterId("공격수")].status.curr_hp == 100
        # 도발자1: 원래 자신을 향한 공격 + 재배정된 공격수 몫 = 2회분.
        assert (
            100 - ctx.characters[CharacterId("도발자1")].status.curr_hp
            == single_hit_damage * 2
        )
        # 도발자2: 원래 자신을 향한 공격만 — 가로채이지 않는다.
        assert (
            100 - ctx.characters[CharacterId("도발자2")].status.curr_hp
            == single_hit_damage
        )


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
            parse_character_command(CharacterId("버퍼"), "[버프 스킬/대상]", ctx)
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
            parse_character_command(CharacterId("버퍼"), "[버프 스킬/대상]", ctx)
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
            parse_character_command(CharacterId("적군"), "[공격/대상]", ctx)
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[버프 스킬/대상]", ctx)
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
            parse_character_command(CharacterId("적군"), "[공격/대상]", ctx)
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[버프 스킬/대상]", ctx)
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
                SkillEffectDamage(
                    ValueSourceType.FIXED, 5, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
        ctx = make_context(buff, skill_dict={"버프 스킬": skill, "약공격": weak_attack})
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
            parse_character_command(CharacterId("적군"), "[약공격/대상]", ctx)
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("버퍼"), "[버프 스킬/대상]", ctx)
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
            effects=[
                SkillEffectHeal(ValueSourceType.FIXED, 1, ValueType.INTEGER, None, None)
            ],
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
            effects=[
                SkillEffectHeal(ValueSourceType.GIVEN_DAMAGE, 50, None, None, None)
            ],
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
            parse_character_command(attacker_id, "[고정 공격/적군]", ctx)
        )

        # 고정 20 대미지의 50% = 10 자기 회복
        assert ctx.characters[attacker_id].status.curr_hp == hp_before + 10

    def test_self_heal_not_double_fired_when_holder_is_also_a_target(self):
        """공격자가 같은 효과 안에서 자기 자신도 대상으로 포함하는 광역/다중
        대상 공격을 사용하면, 공격자 측(ON_ATTACK)과 대상 측(ON_HIT) 양쪽에서
        같은 패시브가 두 번 발동해서는 안 된다."""
        from battle.objects.passive_skill.models import (
            PassiveSkillData,
            PassiveSkillTargetType,
            PassiveSkillTrigger,
        )

        self_included_attack = SkillData(
            id="자해 포함 공격",
            target_rule="SkillTargetRuleNamed",
            target_count=2,
            cost=1,
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
        lifesteal_passive = PassiveSkillData(
            id="생명력 흡수",
            trigger=PassiveSkillTrigger.ON_ACTION,
            target_type=PassiveSkillTargetType.SELF,
            effects=[
                SkillEffectHeal(ValueSourceType.GIVEN_DAMAGE, 50, None, None, None)
            ],
            description="",
        )
        ctx = make_context(
            skill_dict={"자해 포함 공격": self_included_attack},
            passive_skill_dict={"생명력 흡수": lifesteal_passive},
        )
        manager = setup_ally_phase(ctx)

        attacker_id = CharacterId("공격수")
        ctx.add_character(
            get_test_preset(
                "공격수",
                initial_hp=50,
                max_hp=100,
                skill_1_id="자해 포함 공격",
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

        hp_before = ctx.characters[attacker_id].status.curr_hp

        manager.process_command(
            parse_character_command(attacker_id, "[자해 포함 공격/공격수/적군]", ctx)
        )

        # 자신+적군에게 각각 고정 20 대미지 → 자기 피해 20, 총 given damage 40의
        # 50% = 20만큼 자기 회복. 패시브가 중복 발동되면 40이 회복되어 순변화가
        # +20이 아니라 +40이 된다.
        assert ctx.characters[attacker_id].status.curr_hp == hp_before - 20 + 20


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
            effects=[
                SkillEffectHeal(
                    ValueSourceType.GIVEN_HEAL,
                    50,
                    None,
                    None,
                    None,
                    condition_class_name="HealedNonSelfCondition",
                )
            ],
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
            parse_character_command(healer_id, "[회복 스킬/환자]", ctx)
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
            parse_character_command(healer_id, "[회복 스킬/힐러]", ctx)
        )

        # 자기 자신을 회복할 때는 추가 회복이 없으므로 정확히 40만 회복
        assert ctx.characters[healer_id].status.curr_hp == 60
