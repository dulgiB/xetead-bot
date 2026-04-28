from battle.admin_utils import ChangePhaseCommand
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager, RoundPhaseType
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    MagicResistanceType,
)
from battle.objects.models import CharacterId
from spreadsheets.models.battle import CharacterDataFromSpreadsheet

test_context = BattlefieldContext(buff_dict={}, skill_dict={})
test_manager = RoundManager(test_context)


def test_basic():
    test_context.clear()
    print()

    print("\n=============================================\n")

    test_context.add_character(
        _get_test_preset("테스트"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    print(test_context)
    print("\n=============================================\n")

    test_context.remove_character(CharacterId("테스트"))
    print(test_context)


def test_basic_attack():
    test_context.clear()
    print()

    test_manager.process_command(
        ChangePhaseCommand(type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION)
    )
    test_context.add_character(
        _get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    test_context.add_character(
        _get_test_preset("적군 1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )

    print(test_context)
    print("\n=============================================\n")

    test_command = parse_character_command(CharacterId("아군 1"), "[공격/적군 1]")
    test_manager.process_command(test_command)
    print(test_context)


def _get_test_preset(character_name: str) -> CharacterDataFromSpreadsheet:
    return CharacterDataFromSpreadsheet(
        name=character_name,
        mastodon_id="",
        curr_hp=100,
        max_hp=100,
        atk=5,
        attack_range=3,
        m_res=MagicResistanceType.NORMAL,
        is_magic_attacker=False,
        max_cost=3,
        passive_buff_id="",
        skill_1_id="",
        skill_2_id="",
    )
