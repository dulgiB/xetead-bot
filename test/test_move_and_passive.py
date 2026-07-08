import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
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
from battle.objects.passive_skill.passive_skill import PassiveSkillWrapperBuff
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectMove
from battle.objects.skill.effects.effect_move import _move_away_from, _move_toward
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

# ── 상대적 이동 헬퍼 함수 단위 테스트 ────────────────────────────────────────────


def test_move_toward_moves_closer():
    """`_move_toward`는 from_pos를 toward_pos 방향으로 steps만큼 이동시켜야 한다."""
    # COL2(1) → COL4(3) 방향으로 2칸 → COL4(3)
    result = _move_toward(BattlefieldColumnIndex(1), BattlefieldColumnIndex(3), 2)
    assert result == BattlefieldColumnIndex(3)


def test_move_toward_clamps_at_upper_boundary():
    """상한 경계를 넘지 않도록 clamping 되어야 한다."""
    # COL5(4) → COL7(6) 방향으로 5칸 → COL7(6) (최대)
    result = _move_toward(BattlefieldColumnIndex(4), BattlefieldColumnIndex(6), 5)
    assert result == BattlefieldColumnIndex(6)


def test_move_toward_clamps_at_lower_boundary():
    """하한 경계를 넘지 않도록 clamping 되어야 한다."""
    # COL3(2) → COL1(0) 방향으로 5칸 → COL1(0) (최소)
    result = _move_toward(BattlefieldColumnIndex(2), BattlefieldColumnIndex(0), 5)
    assert result == BattlefieldColumnIndex(0)


def test_move_toward_same_position_no_move():
    """동일 위치면 이동이 없어야 한다."""
    result = _move_toward(BattlefieldColumnIndex(3), BattlefieldColumnIndex(3), 2)
    assert result == BattlefieldColumnIndex(3)


def test_move_away_from_moves_farther():
    """`_move_away_from`은 from_pos를 away_from에서 멀어지는 방향으로 이동시켜야 한다."""
    # COL5(4), away_from COL2(1) → COL7(6) 방향으로 2칸 → COL6+1=6 clamped=6
    result = _move_away_from(BattlefieldColumnIndex(4), BattlefieldColumnIndex(1), 2)
    assert result == BattlefieldColumnIndex(6)


def test_move_away_from_clamps_at_lower_boundary():
    """하한 경계 clamping: 이미 COL1(0)에서 뒤로 이동할 수 없으면 그 자리에 있어야 한다."""
    # COL2(1), away_from COL4(3) → 뒤로 3칸 → max(0, 1-3)=0 → COL1
    result = _move_away_from(BattlefieldColumnIndex(1), BattlefieldColumnIndex(3), 3)
    assert result == BattlefieldColumnIndex(0)


def test_move_away_from_same_position_no_move():
    """동일 위치면 이동이 없어야 한다."""
    result = _move_away_from(BattlefieldColumnIndex(3), BattlefieldColumnIndex(3), 1)
    assert result == BattlefieldColumnIndex(3)


# ── TOWARD_HOLDER / AWAY_FROM_HOLDER 통합 테스트 ────────────────────────────────


@pytest.fixture
def pull_skill():
    """대상을 holder 방향으로 2칸 끌어당기는 스킬 (is_forced=True)."""
    return SkillData(
        id="끌어당기기",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[SkillEffectMove(ValueSourceType.TOWARD_HOLDER, 2, None, None, None)],
        description="",
    )


@pytest.fixture
def push_skill():
    """대상을 holder에서 2칸 밀어내는 스킬 (is_forced=True)."""
    return SkillData(
        id="밀어내기",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectMove(ValueSourceType.AWAY_FROM_HOLDER, 2, None, None, None)
        ],
        description="",
    )


def test_toward_holder_skill_moves_target(pull_skill):
    """아군이 끌어당기기 스킬 사용 시 적이 아군 방향으로 이동해야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"끌어당기기": pull_skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")
    # 아군: COL1(0), 적군: COL5(4) → 2칸 당기면 COL3(2)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="끌어당기기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(4)
    )

    cmd = parse_character_command(ally_id, "[스킬/끌어당기기/적군 1]")
    manager.process_command(cmd)

    assert ctx.find_character_position(enemy_id) == BattlefieldColumnIndex(2)


def test_away_from_holder_skill_moves_target(push_skill):
    """아군이 밀어내기 스킬 사용 시 적이 아군에서 멀어져야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"밀어내기": push_skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")
    # 아군: COL1(0), 적군: COL3(2) → 2칸 밀면 COL5(4)
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="밀어내기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(2)
    )

    cmd = parse_character_command(ally_id, "[스킬/밀어내기/적군 1]")
    manager.process_command(cmd)

    assert ctx.find_character_position(enemy_id) == BattlefieldColumnIndex(4)


def test_away_from_holder_boundary_clamping(push_skill):
    """밀어내기 결과가 경계를 초과하면 COL7에서 멈춰야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"밀어내기": push_skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")
    # 아군: COL1(0), 적군: COL6(5) → 2칸 밀면 COL8이 되지만 COL7(6)으로 clamping
    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="밀어내기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(5)
    )

    cmd = parse_character_command(ally_id, "[스킬/밀어내기/적군 1]")
    manager.process_command(cmd)

    assert ctx.find_character_position(enemy_id) == BattlefieldColumnIndex(6)


# ── ON_ENEMY_MOVE 패시브 트리거 ───────────────────────────────────────────────


def _make_intercept_passive(ally_id: CharacterId) -> PassiveSkillWrapperBuff:
    """고정 대미지 10의 견제 패시브 (조건 없음)."""
    passive_data = PassiveSkillData(
        id="견제",
        trigger=PassiveSkillTrigger.ON_ENEMY_MOVE,
        target_type=PassiveSkillTargetType.ATTACKER_OR_TARGET,
        effect=SkillEffectDamage(
            ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
        ),
        condition_class_name=None,
        condition_value=None,
        description="",
    )
    return PassiveSkillWrapperBuff.create(ally_id, passive_data)


def test_voluntary_enemy_move_triggers_passive():
    """적군의 자발적 이동 커맨드가 아군의 ON_ENEMY_MOVE 패시브를 발동시켜야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = RoundManager(ctx)  # ENEMY_PRE_ACTION 시작

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )

    ctx.buff_container.add_passive_wrapper(_make_intercept_passive(ally_id))

    initial_hp = ctx.characters[enemy_id].status.curr_hp

    cmd = parse_character_command(enemy_id, "[이동/2]")
    manager.process_command(cmd)

    assert ctx.characters[enemy_id].status.curr_hp == initial_hp - 10


def test_forced_move_does_not_trigger_passive(pull_skill):
    """강제 이동(스킬 효과)은 ON_ENEMY_MOVE 패시브를 발동시키지 않아야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"끌어당기기": pull_skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="끌어당기기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(4)
    )

    ctx.buff_container.add_passive_wrapper(_make_intercept_passive(ally_id))

    initial_hp = ctx.characters[enemy_id].status.curr_hp

    cmd = parse_character_command(ally_id, "[스킬/끌어당기기/적군 1]")
    manager.process_command(cmd)

    # 강제 이동이므로 패시브 대미지 없음 — HP는 초기값과 같아야 한다
    assert ctx.characters[enemy_id].status.curr_hp == initial_hp


def test_forced_move_updates_moved_this_round(pull_skill):
    """강제 이동도 moved_this_round에 기록되어야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={"끌어당기기": pull_skill})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1", skill_1_id="끌어당기기"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(4)
    )

    assert enemy_id not in ctx.moved_this_round

    cmd = parse_character_command(ally_id, "[스킬/끌어당기기/적군 1]")
    manager.process_command(cmd)

    assert enemy_id in ctx.moved_this_round


def test_passive_only_fires_for_enemy_faction():
    """같은 진영(아군끼리) 이동에는 ON_ENEMY_MOVE 패시브가 발동하지 않아야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )

    ally_id = CharacterId("아군 1")
    ally2_id = CharacterId("아군 2")

    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(3)
    )

    ctx.buff_container.add_passive_wrapper(_make_intercept_passive(ally_id))

    initial_hp = ctx.characters[ally2_id].status.curr_hp

    cmd = parse_character_command(ally2_id, "[이동/2]")
    manager.process_command(cmd)

    # 같은 진영 이동이므로 패시브 미발동 — HP 변화 없음
    assert ctx.characters[ally2_id].status.curr_hp == initial_hp


def test_target_in_range_condition_prevents_out_of_range_trigger():
    """TargetIsInRangeCondition: 사거리 밖 적이 이동하면 패시브가 발동하지 않아야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = RoundManager(ctx)

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")

    # 아군 사거리 1, 아군 COL1, 적군 COL7(6) — 거리 6 > 사거리 1 → 발동 안 함
    ctx.add_character(
        get_test_preset("아군 1", attack_range=1),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(6)
    )

    passive_data = PassiveSkillData(
        id="견제",
        trigger=PassiveSkillTrigger.ON_ENEMY_MOVE,
        target_type=PassiveSkillTargetType.ATTACKER_OR_TARGET,
        effect=SkillEffectDamage(
            ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
        ),
        condition_class_name="TargetIsInRangeCondition",
        condition_value=None,
        description="",
    )
    ctx.buff_container.add_passive_wrapper(
        PassiveSkillWrapperBuff.create(ally_id, passive_data)
    )

    initial_hp = ctx.characters[enemy_id].status.curr_hp

    # 적군이 COL5(4)로 이동 — 아직 거리 4 > 사거리 1 → 발동 안 함
    cmd = parse_character_command(enemy_id, "[이동/5]")
    manager.process_command(cmd)

    assert ctx.characters[enemy_id].status.curr_hp == initial_hp


def test_target_in_range_condition_triggers_when_in_range():
    """TargetIsInRangeCondition: 사거리 내 적이 이동하면 패시브가 발동해야 한다."""
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    manager = RoundManager(ctx)

    ally_id = CharacterId("아군 1")
    enemy_id = CharacterId("적군 1")

    # 아군 사거리 5, 아군 COL1(0), 적군 COL4(3) — 거리 3 ≤ 사거리 5 → 발동
    ctx.add_character(
        get_test_preset("아군 1", attack_range=5),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(3)
    )

    passive_data = PassiveSkillData(
        id="견제",
        trigger=PassiveSkillTrigger.ON_ENEMY_MOVE,
        target_type=PassiveSkillTargetType.ATTACKER_OR_TARGET,
        effect=SkillEffectDamage(
            ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
        ),
        condition_class_name="TargetIsInRangeCondition",
        condition_value=None,
        description="",
    )
    ctx.buff_container.add_passive_wrapper(
        PassiveSkillWrapperBuff.create(ally_id, passive_data)
    )

    initial_hp = ctx.characters[enemy_id].status.curr_hp

    cmd = parse_character_command(enemy_id, "[이동/2]")
    manager.process_command(cmd)

    assert ctx.characters[enemy_id].status.curr_hp == initial_hp - 10


# ── 수호 본능 (ENEMY_POST_ACTION 트리거) ──────────────────────────────────────


def _guard_buff_data() -> "BuffData":
    from battle.objects.buff.models import BuffData

    return BuffData(
        id="수호",
        buff_class_name="BuffReceivedDamage",
        duration_turn_value=1,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=-10,  # 받는 대미지 −10%
        condition_=None,
        condition_value=None,
        is_debuff=False,
        description="",
    )


def _make_guardian_passive(guardian_id: CharacterId) -> PassiveSkillWrapperBuff:
    from battle.objects.skill.effects import SkillEffectAddBuff

    passive_data = PassiveSkillData(
        id="수호 본능",
        trigger=PassiveSkillTrigger.ENEMY_POST_ACTION,
        target_type=PassiveSkillTargetType.SAME_COLUMN_ALLIES,
        effect=SkillEffectAddBuff(
            value_source=None,
            value=None,
            value_type=None,
            buff_id="수호",
            buff_add_timing=None,
        ),
        condition_class_name=None,
        condition_value=None,
        description="",
    )
    return PassiveSkillWrapperBuff.create(guardian_id, passive_data)


def test_guardian_evaluated_at_enemy_post_action_position():
    """수호 본능은 ENEMY_POST_ACTION 시점의 같은 열 아군을 기준으로 경감을 적용한다.

    라운드 시작 시엔 다른 열이던 아군이 ALLY_ACTION에 보호자 열로 이동하면,
    POST 시점 위치 기준으로 보호받아야 한다.
    """
    fixed_attack = SkillData(
        id="강타",
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=0,
        effects=[
            SkillEffectDamage(
                ValueSourceType.FIXED, 50, ValueType.INTEGER, None, None
            )
        ],
        description="",
    )
    ctx = BattlefieldContext(
        buff_dict={"수호": _guard_buff_data()},
        skill_dict={"강타": fixed_attack},
    )
    manager = RoundManager(ctx)  # ENEMY_PRE_ACTION 시작

    guardian_id = CharacterId("아군 1")
    protected_id = CharacterId("아군 2")
    enemy_id = CharacterId("적군 1")

    ctx.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    # 피보호자는 라운드 시작 시 보호자와 다른 열(1)에 있다.
    ctx.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(1)
    )
    ctx.add_character(
        get_test_preset("적군 1", skill_1_id="강타"),
        FactionType.ENEMY, BattlefieldColumnIndex(1),
    )
    ctx.buff_container.add_passive_wrapper(_make_guardian_passive(guardian_id))

    # PRE: 적이 피보호자(1열)에게 강타 선언
    manager.process_command(parse_character_command(enemy_id, "[스킬/강타/아군 2]"))

    # ALLY: 피보호자가 보호자 열(0)로 이동
    manager.to_phase(RoundPhaseType.ALLY_ACTION)
    manager.process_command(parse_character_command(protected_id, "[이동/1]"))
    assert ctx.find_character_position(protected_id) == BattlefieldColumnIndex(0)

    # POST: 같은 열 판정이 이 시점 기준이므로 −10% 경감 (50 → 45)
    manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
    assert ctx.characters[protected_id].status.curr_hp == 55  # 100 - 45
