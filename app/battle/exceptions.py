from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    BattlefieldColumnIndex,
)
from battle.objects.models import CharacterId


class CommandValidationError(Exception):
    pass


def error_too_many_characters(pos: BattlefieldColumnIndex) -> str:
    return f"지정한 위치({pos})에 이미 {CHARACTER_PER_COLUMN}명이 위치하고 있어 이동할 수 없습니다."


def error_target_does_not_exist(target_id: CharacterId) -> str:
    return f"지정한 대상({target_id.name})을 찾을 수 없습니다."


def error_target_is_companion(target_id: CharacterId) -> str:
    return f"지정한 대상({target_id.name})은 직접 대상으로 지정할 수 없습니다."


def error_attack_position_too_far(pos: BattlefieldColumnIndex) -> str:
    return f"지정한 위치({pos})가 공격 가능 범위를 벗어나 공격할 수 없습니다."


def error_invalid_move_destination(pos: BattlefieldColumnIndex) -> str:
    return f"지정한 위치({pos})는 이동 가능한 위치가 아닙니다."


def error_skill_not_registered(skill_name: str) -> str:
    return f"지정한 스킬({skill_name})이 등록되어 있지 않아 사용할 수 없습니다."


def error_no_remaining_cost(needed_cost: int, remaining_cost: int) -> str:
    return f"코스트가 부족하여 사용할 수 없습니다. (필요 코스트: {needed_cost}, 잔여 코스트: {remaining_cost})"


def error_too_many_targets(skill_id: str, max_count: int, actual_count: int) -> str:
    return f"스킬({skill_id})의 최대 대상 수({max_count})를 초과하였습니다. (지정한 대상 수: {actual_count})"


def error_invalid_command_format() -> str:
    return "커맨드가 잘못되었습니다. 형식을 다시 확인해 주세요."


def error_item_does_not_exist(item_id: str) -> str:
    return f"지정한 아이템({item_id})이 등록되어 있지 않아 사용할 수 없습니다."


def error_no_item_in_inventory(item_id: str) -> str:
    return f"지정한 아이템({item_id})을 보유하고 있지 않아 사용할 수 없습니다."


def error_item_not_usable_here() -> str:
    return "이 전투에서는 아이템을 사용할 수 없습니다."


def error_item_has_no_effect() -> str:
    return "사용할 수 없는 아이템입니다."


def error_item_not_usable_in_battle() -> str:
    return "전투 중에는 사용할 수 없는 아이템입니다."


def error_skill_or_item_not_registered() -> str:
    return "등록된 스킬도 아이템도 아닙니다."


def error_character_already_defeated(char_id: CharacterId) -> str:
    return f"'{char_id.name}'은(는) 이미 전투불능(체력 0) 상태이므로 전장에 배치할 수 없습니다."
