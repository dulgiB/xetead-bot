import traceback
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import count_bracket_groups, parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.models import CharacterId

from bot.battle_reply_text import format_battle_reply
from bot.load_data import reveal_declared_enemy_skills
from bot.log_sheets import BattleCommandLog, write_back_changed_hp

if TYPE_CHECKING:
    from bot.main import BotState
    from bot.session import BattleSession


def handle_character_command(
    acct: str,
    text: str,
    state: "BotState",
    session: "BattleSession",
    field_id: str,
    *,
    silent_on_unrecognized: bool = False,
) -> tuple[Optional[str], Optional[BattleCommandLog]]:
    """
    mastodon acct를 char_dict로 캐릭터 ID로 변환 후 커맨드를 파싱·처리한다.
    검증 실패 시 오류 메시지 문자열을 반환한다.

    `session`/`field_id`는 호출측이 명시한다 — 본 전투(`state.session`,
    `str(state.preparation_status_id)`)와 DM 전투(각 `DmBattleState.session`/
    `.field_id`)가 이 함수를 공유하기 위함이다.

    반환값의 두 번째 요소는 로그_전투 기록용 자료다 (전투가 시작되지 않았거나
    캐릭터를 찾지 못하는 등, 커맨드 자체를 시도하지 않은 경우는 None).

    `silent_on_unrecognized=True`면 대괄호 커맨드 자체가 없는 입력(사담 등)에
    대해 에러 문자열 대신 `(None, None)`을 반환한다 — DM 전투처럼 스레드
    하나가 계속 이어지는 구조에서, 참가자가 잡담을 해도 에러 답글로 스레드를
    어지럽히지 않기 위함이다. 본 전투는 페이즈마다 게시물이 바뀌는 구조라
    해당되지 않으므로 기본값은 False로 기존 동작을 유지한다.
    """
    if not session.started:
        return "◊ 전투가 시작되지 않았습니다.", None

    if acct not in state.char_dict:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    char_data = state.char_dict[acct]
    char_id = CharacterId(char_data.name)

    if char_id not in session.context.characters:
        return "◊ 해당 캐릭터는 현재 전장에 배치되지 않았습니다.", None

    phase = session.current_phase
    char = session.context.characters[char_id]
    is_enemy_declare = char.faction.value == "적군"

    if char.faction.value == "아군" and phase != RoundPhaseType.ALLY_ACTION:
        return "◊ 지금은 아군 행동 단계가 아닙니다.", None
    if is_enemy_declare and phase != RoundPhaseType.ENEMY_PRE_ACTION:
        return "◊ 지금은 적군 행동 선언 단계가 아닙니다.", None

    round_n = session.round_n

    if count_bracket_groups(text) >= 2:
        return (
            "◊ 한 메시지에는 대괄호 커맨드를 하나만 입력할 수 있습니다. "
            "여러 스킬/아이템을 한 번에 쓰려면 '[스킬A/대상 - 스킬B]'처럼 "
            "하이픈으로 이어서 한 대괄호 안에 작성해 주세요.",
            None,
        )

    try:
        command = parse_character_command(char_id, text, session.context)
        if command is None:
            if silent_on_unrecognized:
                return None, None
            return (
                "◊ 커맨드 형식을 인식할 수 없습니다. 예: [공격/이름] 또는 [이동/3]",
                None,
            )

        before = len(session.context.results)
        session.context.inventory.cache = state.sheet_cache
        session.process_command(command)
        new_results = session.context.results[before:]
        entries = [entry for result in new_results for entry in result.log_entries]
        write_back_changed_hp(
            state.spreadsheet, session.context, entries, cache=state.sheet_cache
        )

        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            command_text=text,
            entries=entries,
        )
        reply_text = format_battle_reply(
            session.context, char_id, new_results, show_skill_preview=is_enemy_declare
        )
        if is_enemy_declare:
            reveal_declared_enemy_skills(
                state.spreadsheet, session.context, command, cache=state.sheet_cache
            )
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
