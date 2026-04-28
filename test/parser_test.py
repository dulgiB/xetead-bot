import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import try_expansion_if_valid
from battle.core.commands.models import CharacterCommand, CommandPart
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.exceptions import CommandValidationError
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import CharacterId

test_character = CharacterId("테스트")
test_context = BattlefieldContext(buff_dict={}, skill_dict={})
test_manager = RoundManager(test_context)


@pytest.mark.parametrize(
    "command, expected_output",
    [
        ("단순 지문", None),
        (
            "[이동/1]",
            CharacterCommand(
                user_id=test_character,
                parts=[
                    CommandPart(
                        type_=ActionType.MOVE,
                        target_positions=[BattlefieldColumnIndex(0)],
                    )
                ],
            ),
        ),
        (
            "[공격/대상]",
            CharacterCommand(
                user_id=test_character,
                parts=[
                    CommandPart(
                        type_=ActionType.ATTACK,
                        target_characters=[CharacterId("대상")],
                    )
                ],
            ),
        ),
        (
            "[공격 / 띄어쓰기가 있는 대상 ]",
            CharacterCommand(
                user_id=test_character,
                parts=[
                    CommandPart(
                        type_=ActionType.ATTACK,
                        target_characters=[CharacterId("띄어쓰기가 있는 대상")],
                    )
                ],
            ),
        ),
        (
            "[공격/띄어쓰기와 숫자 표기가 있는 대상 1]",
            CharacterCommand(
                user_id=test_character,
                parts=[
                    CommandPart(
                        type_=ActionType.ATTACK,
                        target_characters=[
                            CharacterId("띄어쓰기와 숫자 표기가 있는 대상 1")
                        ],
                    )
                ],
            ),
        ),
        (
            "[ 스킬1 / 대상1       ]",
            CharacterCommand(
                user_id=test_character,
                parts=[
                    CommandPart(
                        type_=ActionType.SKILL_1,
                        target_characters=[CharacterId("대상1")],
                    )
                ],
            ),
        ),
        (
            "[스킬2/ 대상1/  대상2/ 대상 3/대상4   ] 지문",
            CharacterCommand(
                user_id=test_character,
                parts=[
                    CommandPart(
                        type_=ActionType.SKILL_2,
                        target_characters=[
                            CharacterId("대상1"),
                            CharacterId("대상2"),
                            CharacterId("대상 3"),
                            CharacterId("대상4"),
                        ],
                    )
                ],
            ),
        ),
        (
            "[스킬1/1열] 지문",
            CharacterCommand(
                user_id=test_character,
                parts=[
                    CommandPart(
                        type_=ActionType.SKILL_1,
                        target_positions=[BattlefieldColumnIndex(0)],
                    )
                ],
            ),
        ),
    ],
)
def test_parse_smoke(command: str, expected_output: CommandPart):
    parsed_command = parse_character_command(test_character, command)
    assert parsed_command == expected_output


@pytest.mark.parametrize(
    "command", ["[8]", "[대상]", "[스킬1]", "[1/스킬/대상]", "[스킬1/대상]"]
)
def test_parse_invalid(command: str):
    with pytest.raises(CommandValidationError):
        parsed_command = parse_character_command(test_character, command)
        try_expansion_if_valid(test_context, parsed_command)
