from battle.core.commands.admin import (
    ForceAddBuffByIdCommand,
    ForceDamageCommand,
    ForceHealCommand,
    ForceMoveCommand,
    ForceRemoveBuffByIdCommand,
)
from battle.core.round_manager import RoundManager
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffApplyTiming,
    FactionType,
)
from battle.objects.models import CharacterId
from helpers import get_test_preset


def test_force_move_updates_position(empty_context, empty_manager):
    empty_context.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    empty_manager.process_command(
        ForceMoveCommand(
            type_=ActionType.ADMIN,
            targets=[CharacterId("아군 1")],
            to_position=BattlefieldColumnIndex(2),
        )
    )
    assert empty_context.find_character_position(
        CharacterId("아군 1")
    ) == BattlefieldColumnIndex(2)


def test_force_damage_and_heal(empty_context, empty_manager):
    empty_context.add_character(
        get_test_preset("아군 1", max_hp=100),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    empty_manager.process_command(
        ForceDamageCommand(
            type_=ActionType.ADMIN, targets=[CharacterId("아군 1")], damage_value=30
        )
    )
    assert empty_context.characters[CharacterId("아군 1")].status.curr_hp == 70

    empty_manager.process_command(
        ForceHealCommand(
            type_=ActionType.ADMIN, targets=[CharacterId("아군 1")], heal_value=10
        )
    )
    assert empty_context.characters[CharacterId("아군 1")].status.curr_hp == 80


def test_force_add_and_remove_buff(buff_atk_data):
    from battle.core.battlefield_context import BattlefieldContext

    context = BattlefieldContext(
        buff_dict={"공격력 증가": buff_atk_data}, skill_dict={}
    )
    manager = RoundManager(context)
    context.add_character(
        get_test_preset("아군 1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )

    manager.process_command(
        ForceAddBuffByIdCommand(
            type_=ActionType.ADMIN,
            targets=[CharacterId("아군 1")],
            buff_id="공격력 증가",
        )
    )
    buffs = context.buff_container.get_buffs_by(
        CharacterId("아군 1"), BuffApplyTiming.ON_ACTION
    )
    assert len(buffs) == 1

    manager.process_command(
        ForceRemoveBuffByIdCommand(
            type_=ActionType.ADMIN,
            targets=[CharacterId("아군 1")],
            buff_id="공격력 증가",
        )
    )
    buffs = context.buff_container.get_buffs_by(
        CharacterId("아군 1"), BuffApplyTiming.ON_ACTION
    )
    assert len(buffs) == 0
