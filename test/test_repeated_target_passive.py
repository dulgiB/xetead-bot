"""직전 라운드 또는 이번 라운드에 이미 공격한 대상을 다시 공격했을 때만
발동하는 패시브(`SameTargetAsPreviousAttackCondition`)의 적립 동작.

한 커맨드 안에서 같은 대상을 거듭 때리는 경우(`공격-공격-공격`)가 핵심이다 —
`context.results`는 커맨드 하나가 끝나야 채워지므로, 이번 라운드분을 results로
판정하면 같은 커맨드의 두 번째 타격부터도 거짓이 된다.

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/스킬/패시브명 대신 일반화된 이름을
쓴다.
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
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectAddBuff
from helpers import get_test_preset

STACK_BUFF_ID = "StackBuff"
PASSIVE_SKILL_ID = "PassiveSkill"
CONDITION_NAME = "SameTargetAsPreviousAttackCondition"

ATTACKER = CharacterId("아군 1")
TARGET_1 = CharacterId("적군 1")
TARGET_2 = CharacterId("적군 2")


def _make_stack_buff_data() -> BuffData:
    """2턴, 최대 3스택. 그 자체로는 효과가 없는 적립용 버프."""
    return BuffData(
        id=STACK_BUFF_ID,
        buff_class_name="BuffStackingMark",
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=0,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.BUFF,
        description="",
        max_stack=3,
    )


def _make_passive_skill_data() -> PassiveSkillData:
    """이미 공격했던 대상을 다시 공격하면 자신에게 적립 버프를 1스택 부여한다."""
    return PassiveSkillData(
        id=PASSIVE_SKILL_ID,
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=STACK_BUFF_ID,
                buff_add_timing=None,
                condition_class_name=CONDITION_NAME,
            )
        ],
        description="",
    )


def _make_context() -> BattlefieldContext:
    context = BattlefieldContext(
        buff_dict={STACK_BUFF_ID: _make_stack_buff_data()},
        skill_dict={},
        passive_skill_dict={PASSIVE_SKILL_ID: _make_passive_skill_data()},
    )
    context.add_character(
        get_test_preset(ATTACKER.name, max_cost=3, passive_skill_id=PASSIVE_SKILL_ID),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    context.add_character(
        get_test_preset(TARGET_1.name, max_hp=500),
        FactionType.ENEMY,
        BattlefieldColumnIndex(0),
    )
    context.add_character(
        get_test_preset(TARGET_2.name, max_hp=500),
        FactionType.ENEMY,
        BattlefieldColumnIndex(1),
    )
    return context


def _ally_phase_manager(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


def _run(context: BattlefieldContext, manager: RoundManager, text: str) -> None:
    manager.process_command(parse_character_command(ATTACKER, text, context))


def _next_round(context: BattlefieldContext, manager: RoundManager) -> RoundManager:
    """라운드 종료 → 다음 라운드 시작. ENEMY_PRE_ACTION을 거쳐야
    on_start_round()가 돌아 이번 라운드 기록이 지워진다."""
    for phase in (
        RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY,
        RoundPhaseType.ENEMY_PRE_ACTION,
        RoundPhaseType.ALLY_ACTION,
    ):
        manager.process_command(
            ChangePhaseCommand(type_=ActionType.ADMIN, target_phase=phase)
        )
    return manager


def test_repeated_attacks_in_one_command_accumulate_stacks():
    """같은 대상을 세 번 때리면 2스택이 쌓인다 — 첫 타격은 "이미 공격한 대상"이
    아니므로 적립되지 않고, 두 번째·세 번째 타격에서 한 스택씩 붙는다."""
    context = _make_context()
    manager = _ally_phase_manager(context)

    _run(context, manager, "[공격/적군 1 - 공격/적군 1 - 공격/적군 1]")

    assert context.get_buff_stack(ATTACKER, STACK_BUFF_ID) == 2


def test_first_attack_on_each_target_grants_nothing():
    """대상을 바꿔 가며 때리면 어느 쪽도 "이미 공격한 대상"이 아니라 적립이 없다."""
    context = _make_context()
    manager = _ally_phase_manager(context)

    _run(context, manager, "[공격/적군 1 - 공격/적군 2]")

    assert context.get_buff_stack(ATTACKER, STACK_BUFF_ID) == 0


def test_target_attacked_last_round_grants_from_first_attack():
    """직전 라운드에 때린 대상이면 이번 라운드 첫 타격부터 적립된다."""
    context = _make_context()
    manager = _ally_phase_manager(context)
    _run(context, manager, "[공격/적군 1]")
    assert context.get_buff_stack(ATTACKER, STACK_BUFF_ID) == 0

    manager = _next_round(context, manager)
    _run(context, manager, "[공격/적군 1]")

    assert context.get_buff_stack(ATTACKER, STACK_BUFF_ID) == 1


def test_attack_record_does_not_survive_two_rounds():
    """이번 라운드 기록은 라운드가 시작될 때 지워진다 — 두 라운드 전에 때린
    대상은 "이미 공격한 대상"이 아니다."""
    context = _make_context()
    manager = _ally_phase_manager(context)
    _run(context, manager, "[공격/적군 1]")

    manager = _next_round(context, manager)
    _run(context, manager, "[공격/적군 2]")
    stack_after_second_round = context.get_buff_stack(ATTACKER, STACK_BUFF_ID)

    manager = _next_round(context, manager)
    _run(context, manager, "[공격/적군 1]")

    assert context.get_buff_stack(ATTACKER, STACK_BUFF_ID) == stack_after_second_round
