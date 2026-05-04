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
    FactionType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectAddBuff
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

test_context = BattlefieldContext(
    buff_dict={
        "공격력 증가": BuffData(
            id="공격력 증가",
            buff_class_name="BuffAtk",
            duration_type=BuffDurationType.TURN,
            duration_value=3,
            value_type=ValueType.INTEGER,
            value=1,
            condition_=None,
            condition_value=None,
        )
    },
    skill_dict={
        "공격 보조": SkillData(
            "공격 보조",
            "SkillTargetRuleNamed",
            2,
            [
                SkillEffectAddBuff(
                    value_source=None,
                    value=None,
                    value_type=None,
                    buff_id="공격력 증가",
                    buff_add_timing=None,
                )
            ],
        )
    },
)


def test_buff_atk():
    test_manager = RoundManager(test_context)
    print()

    test_manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    test_context.add_character(
        get_test_preset("아군 1", skill_1_id="공격 보조"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    test_context.add_character(
        get_test_preset("아군 2"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    test_context.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    print(test_context)
    print("\n=============================================\n")

    test_command_1 = parse_character_command(CharacterId("아군 1"), "[스킬1/아군 2]")
    test_manager.process_command(test_command_1)

    test_command_2 = parse_character_command(CharacterId("아군 2"), "[공격/적군 1]")
    test_manager.process_command(test_command_2)
    print(test_context)
