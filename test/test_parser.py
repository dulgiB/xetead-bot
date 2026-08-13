import pytest
from battle.core.battlefield_context import BattlefieldContext
from battle.core.command_processors import try_expansion_if_valid
from battle.core.commands.models import CharacterCommand, CommandPart
from battle.core.commands.parser import count_bracket_groups, parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

_USER = CharacterId("테스트")


def _dummy_skill(skill_id: str) -> SkillData:
    return SkillData(
        id=skill_id,
        target_rule="SkillTargetRuleNamed",
        target_count=4,
        cost=0,
        effects=[],
        description="",
    )


@pytest.fixture
def ctx() -> BattlefieldContext:
    """파서가 이름만으로 스킬/아이템을 판별할 수 있도록, 테스트에서 쓰는
    스킬명("스킬1", "스킬2", "스킬_1^!~")을 실제로 보유한 캐릭터를 배치한다."""
    context = BattlefieldContext(
        buff_dict={},
        skill_dict={
            "스킬1": _dummy_skill("스킬1"),
            "스킬2": _dummy_skill("스킬2"),
            "스킬_1^!~": _dummy_skill("스킬_1^!~"),
        },
    )
    context.add_character(
        get_test_preset(
            "테스트", skill_1_id="스킬1", skill_2_id="스킬2", skill_3_id="스킬_1^!~"
        ),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )
    return context


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
        # 스킬1 + 단일 캐릭터 대상 — 키워드 없이 스킬명으로 바로 시작
        (
            "[ 스킬1 / 대상1       ]",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
                        type_=ActionType.SKILL,
                        skill_id="스킬1",
                        targets=[CharacterId("대상1")],
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
                        type_=ActionType.SKILL,
                        skill_id="스킬2",
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
                        type_=ActionType.SKILL,
                        skill_id="스킬1",
                        targets=[BattlefieldColumnIndex(0)],
                    )
                ],
            ),
        ),
        # 스킬2 + 캐릭터 이름과 열이 섞인 대상 — 둘 다 순서대로 보존되어야 한다
        (
            "[스킬2/대상1/2열]",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
                        type_=ActionType.SKILL,
                        skill_id="스킬2",
                        targets=[CharacterId("대상1"), BattlefieldColumnIndex(1)],
                    )
                ],
            ),
        ),
        # 언더스코어와 "!"/"^"/"~"가 포함된 스킬명/대상명 — 실제 캐릭터/스킬 id
        # 명명 규칙에 이 문자들이 쓰이는 경우가 있으므로 파싱 가능해야 한다.
        (
            "[스킬_1^!~/대상_1^!~]",
            CharacterCommand(
                user_id=_USER,
                parts=[
                    CommandPart(
                        type_=ActionType.SKILL,
                        skill_id="스킬_1^!~",
                        targets=[CharacterId("대상_1^!~")],
                    )
                ],
            ),
        ),
    ],
)
def test_parse_smoke(input_str: str, expected: CharacterCommand | None, ctx):
    result = parse_character_command(_USER, input_str, ctx)
    assert result == expected


@pytest.mark.parametrize(
    "input_str",
    [
        "[8]",  # 범위 밖 열 번호
        "[대상]",  # 커맨드 타입도, 등록된 스킬/아이템명도 아님
        "[1/스킬/대상]",  # 잘못된 순서 — "1"은 스킬도 아이템도 아님
    ],
)
def test_parse_invalid(input_str: str, ctx):
    with pytest.raises(CommandValidationError):
        parsed = parse_character_command(_USER, input_str, ctx)
        if parsed:
            try_expansion_if_valid(ctx, parsed)


@pytest.mark.parametrize(
    "input_str, expected_count",
    [
        ("단순 지문", 0),
        ("[공격/대상]", 1),
        ("[스킬1/대상1 - 스킬2/대상2]", 1),  # 여러 파트를 올바르게 하이픈으로 묶은 경우
        ("[공격/대상] [스킬1]", 2),
        (
            "[공격/대상]-[스킬1]",
            2,
        ),  # 대괄호를 나눈 채 하이픈만 바깥에 붙인 경우도 잘못된 형식
    ],
)
def test_count_bracket_groups(input_str: str, expected_count: int):
    assert count_bracket_groups(input_str) == expected_count


def test_multiple_bracket_groups_silently_drops_earlier_ones_without_hyphen(ctx):
    """command_base_format의 두 .*가 모두 탐욕적이라, 대괄호를 하이픈 없이
    두 개로 나눠 보내면 마지막 대괄호만 캡처되고 앞쪽은 에러 없이 조용히
    사라진다 — count_bracket_groups()로 호출측이 미리 걸러야 하는 이유의
    회귀 테스트다."""
    result = parse_character_command(_USER, "[공격/대상] [스킬1]", ctx)
    assert result == CharacterCommand(
        user_id=_USER,
        parts=[CommandPart(type_=ActionType.SKILL, skill_id="스킬1", targets=[])],
    )
