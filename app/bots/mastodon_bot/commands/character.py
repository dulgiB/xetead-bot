from typing import TYPE_CHECKING

from battle.core.commands.parser import parse_character_command
from battle.core.commands.define import RoundPhaseType
from battle.exceptions import CommandValidationError
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from bots.mastodon_bot.main import BotState


def handle_character_command(acct: str, text: str, state: "BotState") -> str:
    """
    mastodon acct를 char_dict로 캐릭터 ID로 변환 후 커맨드를 파싱·처리한다.
    검증 실패 시 오류 메시지 문자열을 반환한다.
    """
    if state.session is None or not state.session.started:
        return "전투가 시작되지 않았습니다."

    if acct not in state.char_dict:
        return "등록된 캐릭터를 찾을 수 없습니다."

    char_data = state.char_dict[acct]
    char_id = CharacterId(char_data.name)

    if char_id not in state.session.context.characters:
        return "해당 캐릭터는 현재 전장에 배치되지 않았습니다."

    phase = state.session.current_phase
    char = state.session.context.characters[char_id]

    if char.faction.value == "아군" and phase != RoundPhaseType.ALLY_ACTION:
        return "지금은 아군 행동 단계가 아닙니다."
    if char.faction.value == "적군" and phase != RoundPhaseType.ENEMY_PRE_ACTION:
        return "지금은 적군 행동 선언 단계가 아닙니다."

    try:
        command = parse_character_command(char_id, text)
        if command is None:
            return "커맨드 형식을 인식할 수 없습니다. 예: [공격/이름] 또는 [이동/3]"
        state.session.process_command(command)
        return str(state.session.context)
    except CommandValidationError as e:
        return str(e)
