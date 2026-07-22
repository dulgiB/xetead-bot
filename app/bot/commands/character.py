import traceback
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.models import CharacterId

from bot.battle_reply_text import format_battle_reply
from bot.log_sheets import BattleCommandLog, write_back_changed_hp

if TYPE_CHECKING:
    from bot.main import BotState


def handle_character_command(
    acct: str, text: str, state: "BotState"
) -> tuple[str, Optional[BattleCommandLog]]:
    """
    mastodon acct를 char_dict로 캐릭터 ID로 변환 후 커맨드를 파싱·처리한다.
    검증 실패 시 오류 메시지 문자열을 반환한다.

    반환값의 두 번째 요소는 로그_전투 기록용 자료다 (전투가 시작되지 않았거나
    캐릭터를 찾지 못하는 등, 커맨드 자체를 시도하지 않은 경우는 None).
    """
    if state.session is None or not state.session.started:
        return "◊ 전투가 시작되지 않았습니다.", None

    if acct not in state.char_dict:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    char_data = state.char_dict[acct]
    char_id = CharacterId(char_data.name)

    if char_id not in state.session.context.characters:
        return "◊ 해당 캐릭터는 현재 전장에 배치되지 않았습니다.", None

    phase = state.session.current_phase
    char = state.session.context.characters[char_id]

    if char.faction.value == "아군" and phase != RoundPhaseType.ALLY_ACTION:
        return "◊ 지금은 아군 행동 단계가 아닙니다.", None
    if char.faction.value == "적군" and phase != RoundPhaseType.ENEMY_PRE_ACTION:
        return "◊ 지금은 적군 행동 선언 단계가 아닙니다.", None

    field_id = str(state.preparation_status_id)
    round_n = state.session.round_n

    try:
        command = parse_character_command(char_id, text, state.session.context)
        if command is None:
            return "◊ 커맨드 형식을 인식할 수 없습니다. 예: [공격/이름] 또는 [이동/3]", None

        before = len(state.session.context.results)
        state.session.process_command(command)
        new_results = state.session.context.results[before:]
        entries = [entry for result in new_results for entry in result.log_entries]
        write_back_changed_hp(state.spreadsheet, state.session.context, entries)

        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            command_text=text,
            entries=entries,
        )
        reply_text = format_battle_reply(state.session.context, char_id, new_results)
        return reply_text, battle_log
    except CommandValidationError as e:
        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            command_text=text,
            error_trace=traceback.format_exc(),
        )
        return f"◊ {e}", battle_log
