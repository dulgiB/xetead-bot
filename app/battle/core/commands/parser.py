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

# ex. [이동/1 - 회복포션/대상A - 공격/대상A]
#
# 스킬·아이템은 키워드 없이 이름만으로 구분한다(스킬 우선, 없으면 아이템).
# "이동"/"공격"은 이름만으로는 종류를 알 수 없어 키워드를 유지한다.

kr_charset = r"\p{HangulJamo}\p{HangulCompatibilityJamo}\p{HangulSyllables}\p{HangulJamoExtendedA}\p{HangulJamoExtendedB}"
# 실제 id에 "_", "!", "^", "~"가 들어가는 스킬·아이템이 있어 모두 허용한다.
# "^"는 문자 클래스 맨 앞에 오면 부정으로 해석되므로 반드시 끝에 둔다.
# "()"는 마크다운 답글에서 언더스코어가 강조로 잘못 파싱되는 문제 때문에
# 구분자 표기를 "이름(테스트)"로 옮겨가는 중이라 함께 허용한다.
name_charset = rf"{kr_charset}0-9A-Za-z_!^~()"

_이동 = whitespace_tolerant_literal("이동")
_공격 = whitespace_tolerant_literal("공격")

command_base_format = regex.compile(r".*\[\s*(?P<command>.+)\s*].*", regex.DOTALL)
# DOTALL이 없으면 나레이션과 커맨드가 다른 문단에 있을 때 두 `.*`가 개행을
# 넘지 못해, 유효한 커맨드가 에러도 없이 사담으로 무시된다.

# command_base_format은 탐욕적이라 "[A] [B]" 입력에서 앞 그룹을 조용히 버린다.
# 파서에 넘기기 전에 이걸로 걸러 명시적 에러를 내야 한다 — 여러 파트는
# "[A - B]"처럼 한 대괄호 안에 이어 쓰는 것이 올바른 문법이다.
_bracket_group = regex.compile(r"\[[^\[\]]*]")


def count_bracket_groups(input_str: str) -> int:
    """입력 텍스트에 포함된 완결된 대괄호 그룹([...]) 개수를 센다."""
    return len(_bracket_group.findall(input_str))


# 이동 :: 이동/1 또는 이동/1열
command_format_move = regex.compile(rf"^\s*{_이동}\s*/\s*(?P<pos>[1-7]열?)\s*$")

# 기본 공격 :: 공격/대상 (운명간섭이면 "공격+/대상")
command_format_attack = regex.compile(
    rf"^\s*{_공격}\s*(?P<fate>\+)?\s*/\s*(?P<target>[{name_charset} ]+)\s*$"
)

# 스킬/아이템 사용 :: 스킬명 또는 아이템명(/대상1/대상2...), 운명간섭이면 "스킬_1+/대상"
# "+"는 name_charset에 없어 탐욕적인 name 그룹이 삼키지 않고 fate로 갈린다.
command_format_skill_or_item = regex.compile(
    rf"^\s*(?P<name>[{name_charset} ]+)\s*(?P<fate>\+)?"
    rf"\s*(/\s*(?P<targets>[{name_charset}/ ]+))?\s*$"
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
                            fate_boost=bool(d["fate"]),
                        )
                    )

                elif match := command_format_skill_or_item.match(command):
                    d = match.capturesdict()
                    name = d["name"][0].strip()
                    fate_boost = bool(d["fate"])
                    if d["targets"] and d["targets"][0]:
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

                    # 스킬명과 아이템명이 우연히 같으면 스킬을 우선한다.
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
                                fate_boost=fate_boost,
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
                                    # 아이템에는 운명간섭을 쓸 수 없지만, 여기서
                                    # 버리면 "+"가 조용히 무시된다 — 검증 단계가
                                    # 명시적으로 에러를 내도록 그대로 넘긴다.
                                    fate_boost=fate_boost,
                                )
                            )
                        else:
                            raise CommandValidationError(
                                error_skill_or_item_not_registered()
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
