import logging
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

from dotenv import load_dotenv
from mastodon import Mastodon, StreamListener

from battle.objects.buff.models import BuffData
from battle.objects.skill.models import SkillData
from bots.mastodon_bot.commands.admin import handle_admin_command
from bots.mastodon_bot.load_data import load_all_data
from bots.mastodon_bot.session import BattleSession
from spreadsheets.models.battle import CharacterDataFromSpreadsheet

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ADMIN_MASTODON_ID: 멘션 계정의 acct 값 (로컬 계정은 "username", 리모트는 "username@domain")
ADMIN_MASTODON_ID: str = os.environ["ADMIN_MASTODON_ID"]

_RE_MENTION = re.compile(r"@\S+")


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


@dataclass
class BotState:
    buff_dict: dict[str, BuffData]
    skill_dict: dict[str, SkillData]
    char_dict: dict[str, CharacterDataFromSpreadsheet]
    session: Optional[BattleSession] = field(default=None)


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

        try:
            command_text = _extract_command(status["content"])
            if not command_text:
                return

            if acct == ADMIN_MASTODON_ID:
                response = handle_admin_command(command_text, self._state)
            else:
                response = self._handle_character_command(acct, command_text)

            self._reply(status_id, acct, status["visibility"], response)

        except Exception:
            logger.exception("멘션 처리 중 오류 (acct=%s, status_id=%s)", acct, status_id)

    def _handle_character_command(self, acct: str, text: str) -> str:
        if acct not in self._state.char_dict:
            return "등록된 캐릭터를 찾을 수 없습니다."
        # 캐릭터 커맨드 처리는 추후 구현
        return "캐릭터 커맨드 처리는 준비 중입니다."

    def _reply(
        self, in_reply_to_id: int, acct: str, visibility: str, text: str
    ) -> None:
        # 원문이 public이면 unlisted로 낮춰 타임라인 오염을 줄인다
        post_visibility = "unlisted" if visibility == "public" else visibility
        self._mastodon.status_post(
            f"@{acct} {text}",
            in_reply_to_id=in_reply_to_id,
            visibility=post_visibility,
        )


def main() -> None:
    buff_dict, skill_dict, char_dict = load_all_data()
    state = BotState(buff_dict=buff_dict, skill_dict=skill_dict, char_dict=char_dict)

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
