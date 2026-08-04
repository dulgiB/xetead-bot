"""희생 방어 (BuffSacrifice) 테스트."""

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
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectAddBuff, SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


@pytest.fixture
def sacrifice_buff_data() -> BuffData:
    """단발 희생 방어 버프 (1회 차단)."""
    return BuffData(
        id="희생 방어",
        buff_class_name="BuffSacrifice",
        duration_turn_value=None,
        duration_count_value=1,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
    )


@pytest.fixture
def sacrifice_skill(sacrifice_buff_data) -> SkillData:
    """아군 1인에게 희생 방어 버프를 부여하는 스킬."""
    return SkillData(
        id="희생 방어",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id="희생 방어",
                buff_add_timing=None,
            )
        ],
        description="",
    )


def _setup(sacrifice_buff_data, sacrifice_skill):
    ctx = BattlefieldContext(
        buff_dict={"희생 방어": sacrifice_buff_data},
        skill_dict={"희생 방어": sacrifice_skill},
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    protector_id = CharacterId("아군 1")
    protected_id = CharacterId("아군 2")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="희생 방어"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    cmd = parse_character_command(protector_id, "[희생 방어/아군 2]", ctx)
    manager.process_command(cmd)

    return ctx, manager, protector_id, protected_id, enemy_id


def test_attack_redirected_to_protector(sacrifice_buff_data, sacrifice_skill):
    """적군의 공격이 보호 대상 대신 보호자에게 가야 한다."""
    ctx, manager, protector_id, protected_id, enemy_id = _setup(
        sacrifice_buff_data, sacrifice_skill
    )

    manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
    cmd = parse_character_command(enemy_id, "[공격/아군 2]", ctx)
    manager.process_command(cmd)

    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    protector_hp = ctx.characters[protector_id].status.curr_hp
    protected_hp = ctx.characters[protected_id].status.curr_hp

    assert protector_hp < 100
    assert protected_hp == 100


def test_sacrifice_buff_expires_after_one_use(sacrifice_buff_data, sacrifice_skill):
    """희생 방어 발동 후 버프가 소진되어야 한다."""
    ctx, manager, protector_id, protected_id, enemy_id = _setup(
        sacrifice_buff_data, sacrifice_skill
    )

    manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
    cmd = parse_character_command(enemy_id, "[공격/아군 2]", ctx)
    manager.process_command(cmd)

    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    remaining = ctx.buff_container.get_buffs_by(protected_id, BuffApplyTiming.ON_ACTION)
    sacrifice_buffs = [b for b in remaining if b.id == "희생 방어"]
    assert len(sacrifice_buffs) == 0


def test_second_attack_hits_protected_after_buff_expires(
    sacrifice_buff_data, sacrifice_skill
):
    """버프 소진 후 두 번째 공격은 피보호자에게 직접 도달해야 한다."""
    ctx, manager, protector_id, protected_id, enemy_id = _setup(
        sacrifice_buff_data, sacrifice_skill
    )

    # 1라운드: 희생 방어 발동 소진
    manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
    manager.process_command(parse_character_command(enemy_id, "[공격/아군 2]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

    protected_hp_after_round1 = ctx.characters[protected_id].status.curr_hp
    assert protected_hp_after_round1 == 100

    # 2라운드: 버프 없으므로 피보호자 직접 피격
    manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
    manager.process_command(parse_character_command(enemy_id, "[공격/아군 2]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.characters[protected_id].status.curr_hp < protected_hp_after_round1


def test_redirect_is_faction_agnostic(sacrifice_buff_data, sacrifice_skill):
    """진영과 무관하게 보호 대상에게 가는 대미지는 보호자로 리다이렉트되어야 한다.

    적군이 희생 방어를 사용한 경우, 아군의 공격이 보호 대상(적군) 대신
    보호자(적군)에게 가야 한다.
    """
    ctx = BattlefieldContext(
        buff_dict={"희생 방어": sacrifice_buff_data},
        skill_dict={"희생 방어": sacrifice_skill},
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    enemy_protector_id = CharacterId("적군 1")
    enemy_protected_id = CharacterId("적군 2")
    ally_id = CharacterId("아군 1")

    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 2"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    ctx.buff_container.add(
        BuffAddData(
            given_by=enemy_protector_id,
            applied_to=enemy_protected_id,
            buff_id="희생 방어",
        )
    )

    # 아군 1이 적군 2 공격 → 적군 1(보호자)이 대신 맞아야 함
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.process_command(parse_character_command(ally_id, "[공격/적군 2]", ctx))

    assert ctx.characters[enemy_protector_id].status.curr_hp < 100
    assert ctx.characters[enemy_protected_id].status.curr_hp == 100


def test_ally_heal_not_redirected(sacrifice_buff_data, sacrifice_skill):
    """아군 힐 스킬은 희생 방어의 영향을 받지 않아야 한다."""
    from battle.objects.skill.effects import SkillEffectHeal

    heal_skill = SkillData(
        id="힐",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectHeal(ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None)
        ],
        description="",
    )
    ctx = BattlefieldContext(
        buff_dict={"희생 방어": sacrifice_buff_data},
        skill_dict={"희생 방어": sacrifice_skill, "힐": heal_skill},
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    protector_id = CharacterId("아군 1")
    protected_id = CharacterId("아군 2")
    healer_id = CharacterId("아군 3")

    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="희생 방어"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 2", initial_hp=50),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 3", skill_1_id="힐"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    manager.process_command(
        parse_character_command(protector_id, "[희생 방어/아군 2]", ctx)
    )
    # 힐은 희생 방어 리다이렉트 대상이 아니므로 보호자(아군 1)에게 가면 안 된다.
    manager.process_command(parse_character_command(healer_id, "[힐/아군 2]", ctx))

    assert ctx.characters[protected_id].status.curr_hp == 70  # 50 + 20
    assert ctx.characters[protector_id].status.curr_hp == 100  # 변화 없음


def test_turn_based_sacrifice_redirects_every_round(sacrifice_skill):
    """turn 기반 희생 방어는 횟수 차감 없이 지속 턴 동안 매 공격을 리다이렉트한다."""
    turn_buff = BuffData(
        id="희생 방어",
        buff_class_name="BuffSacrifice",
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
    )
    ctx, manager, protector_id, protected_id, enemy_id = _setup(
        turn_buff, sacrifice_skill
    )

    manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
    manager.process_command(parse_character_command(enemy_id, "[공격/아군 2]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    protector_hp_round1 = ctx.characters[protector_id].status.curr_hp
    assert protector_hp_round1 < 100
    assert ctx.characters[protected_id].status.curr_hp == 100

    manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)  # turn 2 → 1

    # 2라운드: turn 기반이라 여전히 살아있어 다시 리다이렉트되어야 한다.
    manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
    manager.process_command(parse_character_command(enemy_id, "[공격/아군 2]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.characters[protector_id].status.curr_hp < protector_hp_round1  # 또 피격
    assert ctx.characters[protected_id].status.curr_hp == 100  # 여전히 무사


def test_sacrifice_redirects_attached_debuff(sacrifice_buff_data, sacrifice_skill):
    """적의 대미지+디버프 스킬이 보호 대상을 노리면, 대미지뿐 아니라 딸린 디버프도
    보호자에게 함께 적용되어야 한다."""
    debuff = BuffData(
        id="디버프",
        buff_class_name="BuffNoDamage",
        duration_turn_value=3,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=None,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
    )
    enemy_skill = SkillData(
        id="저주 일격",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
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
    ctx = BattlefieldContext(
        buff_dict={"희생 방어": sacrifice_buff_data, "디버프": debuff},
        skill_dict={"희생 방어": sacrifice_skill, "저주 일격": enemy_skill},
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    protector_id = CharacterId("아군 1")
    protected_id = CharacterId("아군 2")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="희생 방어"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1", skill_1_id="저주 일격"),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )

    manager.process_command(
        parse_character_command(protector_id, "[희생 방어/아군 2]", ctx)
    )

    manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
    manager.process_command(
        parse_character_command(enemy_id, "[저주 일격/아군 2]", ctx)
    )
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.characters[protected_id].status.curr_hp == 100
    assert ctx.characters[protector_id].status.curr_hp < 100

    protected_buffs = ctx.buff_container.get_buffs_by(
        protected_id, BuffApplyTiming.ON_ACTION
    )
    protector_buffs = ctx.buff_container.get_buffs_by(
        protector_id, BuffApplyTiming.ON_ACTION
    )
    assert not any(b.id == "디버프" for b in protected_buffs)
    assert any(b.id == "디버프" for b in protector_buffs)


def test_sacrifice_reduces_redirected_damage():
    """희생 방어의 value(퍼센트)만큼 보호자가 받는 대미지가 경감되어야 한다.

    value=20 → 보호자는 원래 대미지의 80%만 수령. (고정 50 대미지 → 40)
    """
    reducing_sacrifice = BuffData(
        id="희생 방어",
        buff_class_name="BuffSacrifice",
        duration_turn_value=None,
        duration_count_value=1,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=20,
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
    )
    fixed_attack = SkillData(
        id="강타",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(
                value_source=ValueSourceType.FIXED,
                value=50,
                value_type=ValueType.INTEGER,
                buff_id=None,
                buff_add_timing=None,
            )
        ],
        description="",
    )
    ctx = BattlefieldContext(
        buff_dict={"희생 방어": reducing_sacrifice},
        skill_dict={"강타": fixed_attack},
    )
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    protector_id = CharacterId("아군 1")
    protected_id = CharacterId("아군 2")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1", skill_1_id="강타"),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )

    ctx.buff_container.add(
        BuffAddData(given_by=protector_id, applied_to=protected_id, buff_id="희생 방어")
    )

    # 적이 피보호자에게 고정 50 대미지 → 보호자가 −20% 경감된 40 수령
    manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
    manager.process_command(parse_character_command(enemy_id, "[강타/아군 2]", ctx))
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

    assert ctx.characters[protected_id].status.curr_hp == 100  # 피보호자 무사
    assert ctx.characters[protector_id].status.curr_hp == 60  # 100 - 40 (경감 적용)
