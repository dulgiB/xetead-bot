from typing import Optional

import regex
from battle.core.commands.models import CharacterCommand, CommandPart
from battle.exceptions import CommandValidationError, error_invalid_command_format
from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import CharacterId

# 커맨드 작성 예시
# ex. [이동/1 - 스킬/대상A/대상B - 공격/대상A]

kr_charset = r"\p{HangulJamo}\p{HangulCompatibilityJamo}\p{HangulSyllables}\p{HangulJamoExtendedA}\p{HangulJamoExtendedB}"

command_base_format = regex.compile(r".*\[\s*(?P<command>.+)\s*].*")

# 이동 :: 이동/1
command_format_move = regex.compile(r"^\s*이동\s*/\s*(?P<pos>[1-7])\s*$")

# 기본 공격 :: 공격/대상
command_format_attack = regex.compile(
    rf"^\s*공격\s*/\s*(?P<target>[{kr_charset}0-9 ]+)\s*$"
)

# 대상이 지정된 스킬 사용 :: 스킬1/대상1/대상2/대상3
command_format_skill = regex.compile(
    rf"^\s*(?P<skill_type>스킬1|스킬2|스킬3)\s*/\s*(?P<targets>[{kr_charset}0-9/ ]+)\s*$"
)

# 대상이 없는 스킬 사용 :: 스킬2
command_format_skill_no_target = regex.compile(
    r"^\s*(?P<skill_type>스킬1|스킬2|스킬3)\s*$"
)

# 아이템 사용 :: 아이템/아이템 이름(/대상)
command_format_item = regex.compile(
    rf"^\s*아이템\s*/\s*(?P<item_name>[{kr_charset} ]+)s*(/\s*(?P<targets>[{kr_charset}0-9/ ]+))?\s*$"
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
                            target_positions=[move_pos],
                        )
                    )

                elif match := command_format_skill_no_target.match(command):
                    d = match.capturesdict()
                    skill_type = ActionType(d["skill_type"][0])
                    parts.append(CommandPart(type_=skill_type))

                elif match := command_format_attack.match(command):
                    d = match.capturesdict()
                    attack_target = d["target"][0].strip()
                    parts.append(
                        CommandPart(
                            type_=ActionType.ATTACK,
                            target_characters=[CharacterId(attack_target)],
                        )
                    )

                elif match := command_format_skill.match(command):
                    d = match.capturesdict()
                    skill_type = ActionType(d["skill_type"][0])
                    targets_split = d["targets"][0].split("/")
                    character_targets: list[CharacterId] = []
                    column_targets: list[BattlefieldColumnIndex] = []
                    for target in targets_split:
                        try:
                            column_parse = BattlefieldColumnIndex.from_str(
                                target.strip()
                            )
                            column_targets.append(column_parse)
                        except ValueError:
                            character_targets.append(CharacterId(target.strip()))

                    parts.append(
                        CommandPart(
                            type_=skill_type,
                            target_positions=column_targets,
                            target_characters=character_targets,
                        )
                    )

                elif match := command_format_item.match(command):
                    d = match.capturesdict()
                    item_name = d["item_name"][0].strip()
                    if "targets" in d.keys():
                        targets = d["targets"][0].split("/")
                    else:
                        # 대상을 명시하지 않으면 자신에게 사용한 것으로 간주
                        targets = [user_id]
                    parts.append(
                        CommandPart(
                            type_=ActionType.USE_ITEM,
                            item_name=item_name,
                            target_characters=targets,
                        )
                    )

            except ValueError as e:
                print(e)
                raise CommandValidationError(error_invalid_command_format())

        return CharacterCommand(user_id=user_id, parts=parts)

    else:
        return None
