import pytest
from battle.core.commands.models import ActionCommand, CommandBase, MoveCommand
from battle.core.commands.parser import parse
from battle.exceptions import CommandValidationError
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import CharacterId

test_character = CharacterId("테스트")


@pytest.mark.parametrize(
    "command, expected_output",
    [
        ("단순 지문", []),
        (
            "[이동/1]",
            [MoveCommand(user=test_character, to_position=BattlefieldColumnIndex(1))],
        ),
        (
            "[공격/대상]",
            [
                ActionCommand(
                    user=test_character,
                    type_=ActionType.ATTACK,
                    targets=[CharacterId("대상")],
                )
            ],
        ),
        (
            "[공격 / 띄어쓰기가 있는 대상 ]",
            [
                ActionCommand(
                    user=test_character,
                    type_=ActionType.ATTACK,
                    targets=[CharacterId("띄어쓰기가 있는 대상")],
                )
            ],
        ),
        (
            "[공격/띄어쓰기와 숫자 표기가 있는 대상 1]",
            [
                ActionCommand(
                    user=test_character,
                    type_=ActionType.ATTACK,
                    targets=[CharacterId("띄어쓰기와 숫자 표기가 있는 대상 1")],
                )
            ],
        ),
        (
            "[ 스킬1 / 대상1       ]",
            [
                ActionCommand(
                    user=test_character,
                    type_=ActionType.SKILL_1,
                    targets=[CharacterId("대상1")],
                )
            ],
        ),
        (
            "[스킬2/ 대상1/  대상2/ 대상 3/대상4   ] 지문",
            [
                ActionCommand(
                    user=test_character,
                    type_=ActionType.SKILL_2,
                    targets=[
                        CharacterId("대상1"),
                        CharacterId("대상2"),
                        CharacterId("대상 3"),
                        CharacterId("대상4"),
                    ],
                )
            ],
        ),
    ],
)
def test_parse_smoke(command: str, expected_output: CommandBase):
    parsed_command = parse(test_character, command)
    assert parsed_command == expected_output


@pytest.mark.parametrize(
    "command", ["[8]", "[대상]", "[스킬1]", "[1/스킬/대상]", "[스킬1/대상]"]
)
def test_parse_invalid(command: str):
    with pytest.raises(CommandValidationError):
        parse(test_character, command)
