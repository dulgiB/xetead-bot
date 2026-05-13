import pytest
from battle.core.command_processors import try_expansion_if_valid
from battle.core.commands.models import CharacterCommand, CommandPart
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from helpers import get_test_preset

_USER = CharacterId("테스트")


@pytest.fixture(autouse=True)
def setup_character(empty_context):
    """파서 검증에 필요한 테스트 캐릭터를 전장에 배치."""
    empty_context.add_character(
        get_test_preset("테스트"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )


@pytest.mark.parametrize(
    "input_str, expected",
    [
        # 지문만 있는 경우 → None 반환
        ("단순 지문", None),
        # 이동
        (
            "[이동/1]",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
                        type_=ActionType.MOVE, targets=[BattlefieldColumnIndex(0)]
                    )
                ],
            ),
        ),
        # 기본 공격
        (
            "[공격/대상]",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(type_=ActionType.ATTACK, targets=[CharacterId("대상")])
                ],
            ),
        ),
        # 공백이 포함된 대상 이름
        (
            "[공격 / 띄어쓰기가 있는 대상 ]",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
                        type_=ActionType.ATTACK,
                        targets=[CharacterId("띄어쓰기가 있는 대상")],
                    )
                ],
            ),
        ),
        # 숫자가 포함된 대상 이름
        (
            "[공격/띄어쓰기와 숫자 표기가 있는 대상 1]",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
                        type_=ActionType.ATTACK,
                        targets=[CharacterId("띄어쓰기와 숫자 표기가 있는 대상 1")],
                    )
                ],
            ),
        ),
        # 스킬1 + 단일 캐릭터 대상
        (
            "[ 스킬1 / 대상1       ]",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
                        type_=ActionType.SKILL_1, targets=[CharacterId("대상1")]
                    )
                ],
            ),
        ),
        # 스킬2 + 복수 캐릭터 대상 + 후방 지문
        (
            "[스킬2/ 대상1/  대상2/ 대상 3/대상4   ] 지문",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
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
        ),
        # 스킬1 + 열 지정 대상
        (
            "[스킬1/1열] 지문",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
                        type_=ActionType.SKILL_1, targets=[BattlefieldColumnIndex(0)]
                    )
                ],
            ),
        ),
    ],
)
def test_parse_smoke(input_str: str, expected: CharacterCommand | None, empty_context):
    result = parse_character_command(_USER, input_str)
    assert result == expected


@pytest.mark.parametrize(
    "input_str",
    [
        "[8]",  # 범위 밖 열 번호
        "[대상]",  # 커맨드 타입 없이 대상만
        "[1/스킬/대상]",  # 잘못된 순서
    ],
)
def test_parse_invalid(input_str: str, empty_context):
    with pytest.raises(CommandValidationError):
        parsed = parse_character_command(_USER, input_str)
        if parsed:
            try_expansion_if_valid(empty_context, parsed)
