import logging
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

import gspread
from dotenv import load_dotenv
from mastodon import Mastodon, StreamListener

from battle.objects.buff.models import BuffData
from battle.objects.skill.models import SkillData
from battle.core.commands.define import RoundPhaseType
from bots.mastodon_bot.commands.admin import AdminCommandResult, handle_admin_command
from bots.mastodon_bot.commands.character import handle_character_command
from bots.mastodon_bot.load_data import load_all_data
from bots.mastodon_bot.session import BattleSession
from spreadsheets.models.battle import CharacterDataFromSpreadsheet

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# admin의 mastodon acct 값 (로컬 계정: "username", 리모트: "username@domain")
ADMIN_MASTODON_ID: str = os.environ["ADMIN_MASTODON_ID"]

_RE_MENTION = re.compile(r"@\S+")
_MAX_POST_LENGTH = 500

# 커맨드를 수신하는 페이즈 (active_phase_post_id 설정 대상)
_COMMAND_PHASES = {
    RoundPhaseType.ENEMY_PRE_ACTION,
    RoundPhaseType.ALLY_ACTION,
}


class _TextExtractor(HTMLParser):
    """Mastodon 포스트의 HTML 콘텐츠에서 평문을 추출한다."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts).strip()


def _strip_html(html_content: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html_content)
    return extractor.get_text()


def _extract_command(raw_html: str) -> str:
    """HTML 콘텐츠에서 멘션(@...)을 제거하고 커맨드 텍스트만 반환한다."""
    text = _strip_html(raw_html)
    text = _RE_MENTION.sub("", text)
    return text.strip()


def _truncate(text: str) -> str:
    if len(text) <= _MAX_POST_LENGTH:
        return text
    return text[: _MAX_POST_LENGTH - 1] + "…"


@dataclass
class BotState:
    buff_dict: dict[str, BuffData]
    skill_dict: dict[str, SkillData]
    char_dict: dict[str, CharacterDataFromSpreadsheet]  # mastodon_id → data
    name_dict: dict[str, CharacterDataFromSpreadsheet]  # name → data
    spreadsheet: gspread.Spreadsheet
    session: Optional[BattleSession] = None
    preparation_status_id: Optional[int] = None   # [전투 준비] 안내 게시물 ID
    active_phase_post_id: Optional[int] = None    # 현재 페이즈 공지 게시물 ID
    battle_key: Optional[str] = None
    pending_participants: list[str] = field(default_factory=list)   # mastodon_ids
    pending_placements: list[tuple] = field(default_factory=list)   # (name, faction, column)


class MastodonBotListener(StreamListener):
    def __init__(self, mastodon: Mastodon, state: BotState) -> None:
        super().__init__()
        self._mastodon = mastodon
        self._state = state

    def on_notification(self, notification: dict) -> None:
        if notification["type"] != "mention":
            return

        account = notification["account"]
        status = notification["status"]
        acct: str = account["acct"]
        status_id: int = status["id"]
        in_reply_to_id: Optional[int] = status.get("in_reply_to_id")

        try:
            command_text = _extract_command(status["content"])
            if not command_text:
                return

            self._dispatch(acct, status_id, in_reply_to_id, command_text, status["visibility"])
        except Exception:
            logger.exception("멘션 처리 중 오류 (acct=%s, status_id=%s)", acct, status_id)

    def _dispatch(
        self,
        acct: str,
        status_id: int,
        in_reply_to_id: Optional[int],
        text: str,
        visibility: str,
    ) -> None:
        state = self._state

        # 1. admin 직접 멘션 → admin 커맨드
        if acct == ADMIN_MASTODON_ID:
            result: AdminCommandResult = handle_admin_command(text, state)

            # admin 답글 전송
            reply_status = self._reply(status_id, acct, visibility, result.reply_text)

            # [전투 준비] 답글 자체를 참전 신청 스레드로 사용
            if result.set_preparation_post:
                state.preparation_status_id = reply_status["id"]

            # 퍼블릭 게시물 게시 (페이즈 게시물)
            if result.game_post_text is not None:
                new_post = self._mastodon.status_post(
                    _truncate(result.game_post_text),
                    visibility="public",
                )
                new_post_id = new_post["id"]

                # 커맨드를 수신하는 페이즈만 active_phase_post_id 설정
                if state.session is not None and state.session.started:
                    if state.session.current_phase in _COMMAND_PHASES:
                        state.active_phase_post_id = new_post_id
                    else:
                        state.active_phase_post_id = None

            return

        # 2. 전투 준비 참전 신청 (bot 준비 게시물에 대한 답글)
        if (
            state.preparation_status_id is not None
            and in_reply_to_id == state.preparation_status_id
        ):
            if acct in state.char_dict and acct not in state.pending_participants:
                state.pending_participants.append(acct)
                logger.info("참전 신청: %s (%s)", acct, state.char_dict[acct].name)
            return

        # 3. 전투 중 캐릭터 커맨드 (active_phase_post_id에 대한 답글)
        if (
            state.active_phase_post_id is not None
            and in_reply_to_id == state.active_phase_post_id
        ):
            response = handle_character_command(acct, text, state)
            self._reply(status_id, acct, visibility, response)
            return

    def _reply(
        self, in_reply_to_id: int, acct: str, visibility: str, text: str
    ) -> dict:
        post_visibility = "unlisted" if visibility == "public" else visibility
        return self._mastodon.status_post(
            f"@{acct} {_truncate(text)}",
            in_reply_to_id=in_reply_to_id,
            visibility=post_visibility,
        )


def main() -> None:
    buff_dict, skill_dict, char_dict, name_dict, spreadsheet = load_all_data()
    state = BotState(
        buff_dict=buff_dict,
        skill_dict=skill_dict,
        char_dict=char_dict,
        name_dict=name_dict,
        spreadsheet=spreadsheet,
    )

    mastodon = Mastodon(
        access_token=os.environ["MASTODON_ACCESS_TOKEN"],
        api_base_url=os.environ["MASTODON_API_BASE_URL"],
    )

    me = mastodon.me()
    logger.info("봇 시작: @%s", me["acct"])
    logger.info("등록된 캐릭터: %d명", len(char_dict))

    mastodon.stream_user(MastodonBotListener(mastodon, state))


if __name__ == "__main__":
    main()
