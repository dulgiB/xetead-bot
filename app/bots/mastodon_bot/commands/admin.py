import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bots.mastodon_bot.main import BotState


_RE_BATTLE_START = re.compile(r"\[전투\s*시작\]")


def handle_admin_command(text: str, state: "BotState") -> str:
    """
    어드민 커맨드 텍스트를 파싱해 처리하고 응답 문자열을 반환한다.
    state를 직접 변경할 수 있다.
    """
    if _RE_BATTLE_START.search(text):
        return _cmd_battle_start(state)

    return "알 수 없는 관리자 커맨드입니다."


def _cmd_battle_start(state: "BotState") -> str:
    from bots.mastodon_bot.session import BattleSession

    if state.session is not None:
        return "이미 진행 중인 세션이 있습니다."

    state.session = BattleSession(state.buff_dict, state.skill_dict)
    return (
        "전투 세션이 생성되었습니다.\n"
        f"등록된 캐릭터: {len(state.char_dict)}명\n"
        "캐릭터 배치 후 [전투 시작/확정]을 입력하면 전투가 시작됩니다."
    )
