from typing import TYPE_CHECKING, Optional

import regex
from battle.core.commands.models import CharacterCommand, CommandPart
from battle.exceptions import (
    CommandValidationError,
    error_invalid_command_format,
    error_skill_or_item_not_registered,
)
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import CharacterId
from utils.name_matching import whitespace_tolerant_literal

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext

# 커맨드 작성 예시
# ex. [이동/1 - 회복포션/대상A - 공격/대상A]
#
# "스킬"/"아이템"은 별도 키워드 없이 이름 자체로 구분한다: 시전자가 보유한
# 스킬 목록에서 먼저 찾고, 없으면 등록된 아이템에서 찾는다(둘 다 없으면
# 오류). "이동"/"공격"은 이름만으로는 종류를 알 수 없으므로 키워드를
# 그대로 유지한다.

kr_charset = r"\p{HangulJamo}\p{HangulCompatibilityJamo}\p{HangulSyllables}\p{HangulJamoExtendedA}\p{HangulJamoExtendedB}"
# 캐릭터/스킬/아이템 id에 언더스코어가 포함되는 경우(예: "스킬_1")가 있어
# 이름·대상에 쓰이는 문자 집합에도 언더스코어를 포함한다. 마찬가지로
# "!"가 들어간 스킬명(예: "스킬_1!")도 있어 함께 포함한다.
name_charset = rf"{kr_charset}0-9A-Za-z_!"

_이동 = whitespace_tolerant_literal("이동")
_공격 = whitespace_tolerant_literal("공격")

command_base_format = regex.compile(r".*\[\s*(?P<command>.+)\s*].*")

# command_base_format의 두 .* 가 모두 탐욕적이라, 대괄호 그룹이 여러 개인
# 입력("[A] [B]")은 마지막 그룹만 command로 캡처되고 앞쪽은 조용히 버려진다
# (에러도 없이). 캐릭터 계정 멘션에서는 이 상태로 파서에 넘기지 말고
# count_bracket_groups()로 미리 걸러 명시적 에러를 내야 한다 — 여러 파트는
# "[A - B]"처럼 하이픈으로 이어 한 대괄호 안에 작성하는 것이 올바른 문법이다.
_bracket_group = regex.compile(r"\[[^\[\]]*]")


def count_bracket_groups(input_str: str) -> int:
    """입력 텍스트에 포함된 완결된 대괄호 그룹([...]) 개수를 센다."""
    return len(_bracket_group.findall(input_str))

# 이동 :: 이동/1 또는 이동/1열
command_format_move = regex.compile(rf"^\s*{_이동}\s*/\s*(?P<pos>[1-7]열?)\s*$")

# 기본 공격 :: 공격/대상
command_format_attack = regex.compile(
    rf"^\s*{_공격}\s*/\s*(?P<target>[{name_charset} ]+)\s*$"
)

# 스킬/아이템 사용 :: 스킬명 또는 아이템명(/대상1/대상2...) — 키워드 없이 이름으로 바로 시작
command_format_skill_or_item = regex.compile(
    rf"^\s*(?P<name>[{name_charset} ]+)\s*(/\s*(?P<targets>[{name_charset}/ ]+))?\s*$"
)


def parse_character_command(
    user_id: CharacterId, input_str: str, context: "BattlefieldContext"
) -> Optional[CharacterCommand]:
    if match := command_base_format.match(input_str):
        d = match.capturesdict()
        command_str = d["command"][0].strip()
        command_list = command_str.split("-")
        parts: list[CommandPart] = []

        for command in command_list:
            try:
                if match := command_format_move.match(command):
                    d = match.capturesdict()
                    move_pos = BattlefieldColumnIndex.from_str(d["pos"][0])
                    parts.append(
                        CommandPart(
                            type_=ActionType.MOVE,
                            targets=[move_pos],
                        )
                    )

                elif match := command_format_attack.match(command):
                    d = match.capturesdict()
                    attack_target = d["target"][0].strip()
                    parts.append(
                        CommandPart(
                            type_=ActionType.ATTACK,
                            targets=[CharacterId(attack_target)],
                        )
                    )

                elif match := command_format_skill_or_item.match(command):
                    d = match.capturesdict()
                    name = d["name"][0].strip()
                    if d["targets"] and d["targets"][0]:
                        # 캐릭터 이름 또는 열(column)로 변환한다.
                        targets: list[CharacterId | BattlefieldColumnIndex] = []
                        for target in d["targets"][0].split("/"):
                            try:
                                targets.append(
                                    BattlefieldColumnIndex.from_str(target.strip())
                                )
                            except ValueError:
                                targets.append(CharacterId(target.strip()))
                    else:
                        targets = []

                    # 시전자가 보유한 스킬 목록에서 먼저 찾고, 없으면 등록된
                    # 아이템에서 찾는다. 스킬명/아이템명이 우연히 같더라도
                    # 스킬을 우선한다.
                    user = context.characters.get(user_id)
                    resolved_skill_id = context.resolve_skill_id(user_id, name)
                    if user is not None and any(
                        s.data.id == resolved_skill_id for s in user.skills
                    ):
                        parts.append(
                            CommandPart(
                                type_=ActionType.SKILL,
                                skill_id=resolved_skill_id,
                                targets=targets,
                            )
                        )
                    else:
                        resolved_item_id = context.resolve_item_id(name)
                        if context.has_item(resolved_item_id):
                            parts.append(
                                CommandPart(
                                    type_=ActionType.USE_ITEM,
                                    item_id=resolved_item_id,
                                    # 대상을 명시하지 않으면 자신에게 사용한 것으로 간주
                                    targets=targets or [user_id],
                                )
                            )
                        else:
                            raise CommandValidationError(
                                error_skill_or_item_not_registered(name)
                            )

                else:
                    raise CommandValidationError(error_invalid_command_format())

            except CommandValidationError:
                raise
            except Exception as e:
                print(e)
                raise CommandValidationError(error_invalid_command_format())

        return CharacterCommand(user_id=user_id, parts=parts)

    else:
        return None
