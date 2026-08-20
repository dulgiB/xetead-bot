"""대련(PracticeRoundManager)에서 ENEMY_POST_ACTION_RESOLVED 트리거 패시브가
정상적으로 발동하는지 확인한다.

배경: PracticeRoundManager는 선공/후공을 process_ally_command()로 즉시
처리할 뿐, 본 전투(RoundManager)가 ENEMY_POST_ACTION 페이즈에서 호출하는
buff_container.on_enemy_post_action()/on_enemy_post_action_resolved()를
전혀 호출하지 않았다 — 그 결과 이 타이밍(예: 피격 시 [재앙] 스택을 쌓는
패시브)을 쓰는 패시브가 대련에서는 한 번도 발동하지 않는 문제가 있었다.
test_catastrophe_full_skillset.py(본 전투)의 TestPassiveSkill과 동일한
버프/패시브 데이터를 대련 컨텍스트에 그대로 옮겨, PracticeRoundManager가
라운드 종료 시 이 훅을 호출하도록 고친 뒤에도 같은 결과가 나오는지
검증한다.

선공/후공은 라운드 시작 시 무작위로 정해지므로, 두 테스트 모두 실제
공격자가 어느 쪽으로 배정되든 FIRST_MOVER_ACTION → SECOND_MOVER_ACTION
→ end_round() 순서를 그대로 따라간다(공격자가 아닌 쪽 페이즈는 그냥
아무 커맨드도 넣지 않고 넘어간다)."""

from battle.core.commands.parser import parse_character_command
from battle.objects.buff.models import BuffData, PassiveBuffData
from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager
from helpers import get_test_preset


def _buff_dict() -> dict[str, BuffData]:
    return {
        "재앙": BuffData.from_dict(
            {
                "id": "재앙",
                "buff_name": "BuffCatastrophe",
                "duration_turn_value": "",
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": "",
                "value_type_0": "",
                "condition": "",
                "condition_value": "",
                "description": "",
                "is_debuff": False,
                "max_stack": 10,
            }
        ),
    }


def _passive_skill_dict() -> dict[str, PassiveSkillData]:
    passive_buff_dict = {
        "PassiveBuff": PassiveBuffData.from_dict(
            {
                "id": "PassiveBuff",
                "buff_name": "BuffReceivedDamage",
                "value_0": -5,
                "value_type_0": "퍼센트",
            }
        ),
    }
    return {
        "PassiveSkill": PassiveSkillData.from_dict(
            {
                "id": "PassiveSkill",
                "trigger": "적 후행 시",
                "target_type": "자신을 포함한 같은 열 아군",
                "buff_id": "PassiveBuff",
                "effect_0": "SkillEffectAddBuff",
                "value_source_0": "",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "재앙",
                "target_override_0": "자신",
                "condition_0": "AllyInSameColumnWasAttackedCondition",
                "condition_value_0": "",
                "effect_1": "SkillEffectAddBuff",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "재앙",
                "target_override_1": "자신",
                "condition_1": "HolderWasAttackedCondition",
                "condition_value_1": "",
                "description": "",
            },
            passive_buff_dict,
        ),
    }


def _make_context() -> PracticeBattlefieldContext:
    return PracticeBattlefieldContext(
        buff_dict=_buff_dict(),
        skill_dict={},
        passive_skill_dict=_passive_skill_dict(),
    )


def _play_round_with_attack(
    manager: PracticeRoundManager,
    ctx: PracticeBattlefieldContext,
    attacker_side: SideType,
    command_text: str,
) -> None:
    """FIRST_MOVER_ACTION → SECOND_MOVER_ACTION → end_round() 순서를 그대로
    따라가며, attacker_side 차례에만 command_text를 실행한다."""
    manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
    if manager.first_mover == attacker_side:
        manager.process_command(
            parse_character_command(CharacterId("적군"), command_text, ctx)
        )
    manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
    if manager.second_mover == attacker_side:
        manager.process_command(
            parse_character_command(CharacterId("적군"), command_text, ctx)
        )
    manager.end_round()


def test_stack_gained_when_same_column_ally_is_hit():
    ctx = _make_context()
    manager = PracticeRoundManager(ctx)

    catastrophe_id = CharacterId("Catastrophe")
    ctx.add_character(
        get_test_preset("Catastrophe", passive_skill_id="PassiveSkill"),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("동료"), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군"), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )

    _play_round_with_attack(manager, ctx, SideType.SIDE_2, "[공격/동료]")

    # 동료(같은 열)가 맞았으므로 1스택, 자신은 맞지 않았으므로 추가 스택은 없다.
    assert ctx.get_buff_stack(catastrophe_id, "재앙") == 1


def test_extra_stack_gained_when_holder_itself_is_hit():
    ctx = _make_context()
    manager = PracticeRoundManager(ctx)

    catastrophe_id = CharacterId("Catastrophe")
    ctx.add_character(
        get_test_preset("Catastrophe", passive_skill_id="PassiveSkill"),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("적군"), SideType.SIDE_2, BattlefieldColumnIndex(0)
    )

    _play_round_with_attack(manager, ctx, SideType.SIDE_2, "[공격/Catastrophe]")

    # 같은 열 피격(효과 0) + 자신 피격(효과 1) 둘 다 조건을 만족해 2스택.
    assert ctx.get_buff_stack(catastrophe_id, "재앙") == 2
