from battle.objects.define import ActionType, BattlefieldColumnIndex
from battle.objects.models import CharacterId


class CommandValidationError(Exception):
    pass


def error_too_many_characters(pos: BattlefieldColumnIndex) -> str:
    return f"지정한 위치({pos})에 이미 2명이 위치하고 있어 이동할 수 없습니다."


def error_target_does_not_exist(target_id: CharacterId) -> str:
    return f"지정한 대상({target_id.name})을 찾을 수 없습니다."


def error_attack_position_too_far(pos: BattlefieldColumnIndex) -> str:
    return f"지정한 위치({pos})가 공격 가능 범위를 벗어나 공격할 수 없습니다."


def error_skill_not_registered(skill_type: ActionType) -> str:
    return f"지정한 스킬({skill_type.value})이 등록되어 있지 않아 사용할 수 없습니다."


def error_no_remaining_cost(needed_cost: int, remaining_cost: int) -> str:
    return f"코스트가 부족하여 사용할 수 없습니다. (필요 코스트: {needed_cost}, 잔여 코스트: {remaining_cost})"


def error_invalid_command_format() -> str:
    return "커맨드가 잘못되었습니다. 형식을 다시 확인해 주세요."
