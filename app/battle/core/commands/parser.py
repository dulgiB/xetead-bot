from typing import Optional

import regex
from battle.core.commands.models import CharacterCommand, CommandPart
from battle.exceptions import CommandValidationError, error_invalid_command_format
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import CharacterId
from utils.name_matching import whitespace_tolerant_literal

# 커맨드 작성 예시
# ex. [이동/1 - 스킬/대상A/대상B - 공격/대상A]

kr_charset = r"\p{HangulJamo}\p{HangulCompatibilityJamo}\p{HangulSyllables}\p{HangulJamoExtendedA}\p{HangulJamoExtendedB}"
# 캐릭터/스킬/아이템 id에 언더스코어가 포함되는 경우(예: "스킬_1")가 있어
# 이름·대상에 쓰이는 문자 집합에도 언더스코어를 포함한다.
name_charset = rf"{kr_charset}0-9A-Za-z_"

_이동 = whitespace_tolerant_literal("이동")
_공격 = whitespace_tolerant_literal("공격")
_스킬 = whitespace_tolerant_literal("스킬")
_아이템 = whitespace_tolerant_literal("아이템")

command_base_format = regex.compile(r".*\[\s*(?P<command>.+)\s*].*")

# 이동 :: 이동/1 또는 이동/1열
command_format_move = regex.compile(rf"^\s*{_이동}\s*/\s*(?P<pos>[1-7]열?)\s*$")

# 기본 공격 :: 공격/대상
command_format_attack = regex.compile(
    rf"^\s*{_공격}\s*/\s*(?P<target>[{name_charset} ]+)\s*$"
)

# 대상이 지정된 스킬 사용 :: 스킬/스킬명/대상1/대상2/대상3
command_format_skill = regex.compile(
    rf"^\s*{_스킬}\s*/\s*(?P<skill_name>[{name_charset} ]+)\s*/\s*(?P<targets>[{name_charset}/ ]+)\s*$"
)

# 대상이 없는 스킬 사용 :: 스킬/스킬명
command_format_skill_no_target = regex.compile(
    rf"^\s*{_스킬}\s*/\s*(?P<skill_name>[{name_charset} ]+)\s*$"
)

# 아이템 사용 :: 아이템/아이템 이름(/대상)
command_format_item = regex.compile(
    rf"^\s*{_아이템}\s*/\s*(?P<item_name>[{name_charset} ]+)\s*(/\s*(?P<targets>[{name_charset}/ ]+))?\s*$"
)


def parse_character_command(
    user_id: CharacterId, input_str: str
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

                elif match := command_format_skill.match(command):
                    d = match.capturesdict()
                    skill_name = d["skill_name"][0].strip()
                    # 아이템과 동일하게 열(column) 또는 캐릭터 이름으로 변환한다.
                    targets: list[CharacterId | BattlefieldColumnIndex] = []
                    for target in d["targets"][0].split("/"):
                        try:
                            targets.append(
                                BattlefieldColumnIndex.from_str(target.strip())
                            )
                        except ValueError:
                            targets.append(CharacterId(target.strip()))

                    parts.append(
                        CommandPart(
                            type_=ActionType.SKILL,
                            skill_id=skill_name,
                            targets=targets,
                        )
                    )

                elif match := command_format_skill_no_target.match(command):
                    d = match.capturesdict()
                    skill_name = d["skill_name"][0].strip()
                    parts.append(
                        CommandPart(type_=ActionType.SKILL, skill_id=skill_name)
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

                elif match := command_format_item.match(command):
                    d = match.capturesdict()
                    item_name = d["item_name"][0].strip()
                    if d["targets"]:
                        # 스킬과 동일하게 열(column) 또는 캐릭터 이름으로 변환한다.
                        targets = []
                        for target in d["targets"][0].split("/"):
                            try:
                                targets.append(
                                    BattlefieldColumnIndex.from_str(target.strip())
                                )
                            except ValueError:
                                targets.append(CharacterId(target.strip()))
                    else:
                        # 대상을 명시하지 않으면 자신에게 사용한 것으로 간주
                        targets = [user_id]
                    parts.append(
                        CommandPart(
                            type_=ActionType.USE_ITEM,
                            item_id=item_name,
                            targets=targets,
                        )
                    )

                else:
                    raise CommandValidationError(error_invalid_command_format())

            except Exception as e:
                print(e)
                raise CommandValidationError(error_invalid_command_format())

        return CharacterCommand(user_id=user_id, parts=parts)

    else:
        return None
