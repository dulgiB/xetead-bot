from typing import Optional

from battle.admin_utils import ChangePhaseCommand
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager, RoundPhaseType
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


def test_basic():
    test_context = BattlefieldContext(buff_dict={}, skill_dict={})
    print()

    print("\n=============================================\n")

    test_context.add_character(
        get_test_preset("테스트"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    print(test_context)
    print("\n=============================================\n")

    test_context.remove_character(CharacterId("테스트"))
    print(test_context)


def test_basic_attack():
    test_context = BattlefieldContext(buff_dict={}, skill_dict={})
    test_manager = RoundManager(test_context)
    print()

    test_manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    test_context.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    test_context.add_character(
        get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    print(test_context)
    print("\n=============================================\n")

    test_command = parse_character_command(CharacterId("아군 1"), "[공격/적군 1]")
    test_manager.process_command(test_command)
    print(test_context)
