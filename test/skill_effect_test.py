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
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectHeal
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

test_context = BattlefieldContext(
    buff_dict={},
    skill_dict={
        "강타": SkillData(
            "강타",
            "SkillTargetRuleNamed",
            2,
            [
                SkillEffectDamage(
                    ValueSourceType.STAT_ATK_ROLL, 20, ValueType.PERCENT, None, None
                )
            ],
        ),
        "회복": SkillData(
            "회복",
            "SkillTargetRuleNamed",
            2,
            [SkillEffectHeal(ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None)],
        ),
    },
)


def test_skill_effect_damage():
    test_manager = RoundManager(test_context)
    print()

    test_manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    test_context.add_character(
        get_test_preset("아군 1", skill_1_id="강타"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    test_context.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    print(test_context)
    print("\n=============================================\n")

    test_command = parse_character_command(CharacterId("아군 1"), "[스킬1/적군 1]")
    test_manager.process_command(test_command)
    print(test_context)


def test_skill_effect_heal():
    test_manager = RoundManager(test_context)
    print()

    test_manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    test_context.add_character(
        get_test_preset("아군 1", skill_1_id="회복"),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    test_context.add_character(
        get_test_preset("아군 2", initial_hp=80),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )

    print(test_context)
    print("\n=============================================\n")

    test_command = parse_character_command(CharacterId("아군 1"), "[스킬1/아군 2]")
    test_manager.process_command(test_command)
    print(test_context)
