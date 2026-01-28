import copy

from battle.admin_utils import ChangePhaseCommand
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import ActionCommand
from battle.core.round_manager import RoundManager, RoundPhaseType
from battle.objects.character.combat_character import CombatCharacter, CombatStats
from battle.objects.define import (
    ActionType,
    BattlefieldSlotIndex,
    FactionType,
    MagicResistanceType,
)
from battle.objects.models import CharacterId

test_context = BattlefieldContext()
test_manager = RoundManager(test_context)

test_stat_preset = CombatStats(
    attack=3,
    max_hp=100,
    attack_range=2,
    magic_resistance=MagicResistanceType.NORMAL,
    max_cost=3,
)


def test_basic():
    test_context.clear()
    print()

    print("\n=============================================\n")

    test_character = CombatCharacter(
        test_context,
        "테스트",
        FactionType.ALLY,
        test_stat_preset,
    )
    test_context.add_character(test_character, BattlefieldSlotIndex(0))
    print(test_context)
    print("\n=============================================\n")

    test_context.remove_character(CharacterId("테스트"))
    print(test_context)


def test_basic_attack():
    test_context.clear()
    print()

    test_manager.process_command(ChangePhaseCommand(RoundPhaseType.ALLY_ACTION))

    test_character_1 = CombatCharacter(
        test_context,
        "아군 1",
        FactionType.ALLY,
        copy.deepcopy(test_stat_preset),
    )

    test_character_2 = CombatCharacter(
        test_context,
        "적군 1",
        FactionType.ENEMY,
        copy.deepcopy(test_stat_preset),
    )

    test_context.add_character(test_character_1, BattlefieldSlotIndex(0))
    test_context.add_character(test_character_2, BattlefieldSlotIndex(0))

    print(test_context)
    print("\n=============================================\n")

    test_command = ActionCommand(
        user=CharacterId("아군 1"),
        type_=ActionType.ATTACK,
        targets=[CharacterId("적군 1")],
    )

    test_manager.process_command(test_command)
    print(test_context)
