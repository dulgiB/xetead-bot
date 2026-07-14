import logging
import os
import re
import traceback
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

import gspread
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import CharacterId
from battle.practice.define import PracticeRoundPhase, SideType
from dotenv import load_dotenv
from mastodon import Mastodon, StreamListener
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet
from utils.name_matching import whitespace_tolerant_literal

from bot.commands.admin import AdminCommandResult, handle_admin_command
from bot.commands.character import handle_character_command
from bot.commands.noncombat import (
    finalize_daily_quest_mid,
    finalize_investigation_menu_post,
    finalize_investigation_overview_post,
    handle_daily_quest_roll,
    handle_daily_quest_start,
    handle_investigation_accept,
    handle_investigation_start,
    handle_investigation_venue_choice,
    handle_roll,
    handle_transfer_item,
    handle_use_item,
    parse_stat_name,
    parse_transfer_item_args,
    parse_use_item_args,
)
from bot import log_sheets
from bot.load_data import load_all_data, load_char_data
from bot.noncombat_state import NonCombatState
from bot.practice_state import PracticeBattleState
from bot.session import BattleSession

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# admin의 mastodon acct 값 (로컬 계정: "username", 리모트: "username@domain")
ADMIN_MASTODON_ID: str = os.environ["ADMIN_MASTODON_ID"]

_RE_MENTION = re.compile(r"@\S+")
_RE_DECLARATION = re.compile(
    rf"\[([12]){whitespace_tolerant_literal('팀')}\s*/\s*([1-7])열?]"
)
_RE_INVESTIGATION_DECLARATION = re.compile(
    rf"\[{whitespace_tolerant_literal('아군')}\s*/\s*([1-7])열?]"
)
_RE_INVESTIGATION_BATTLE_SELF = re.compile(
    rf"\[{whitespace_tolerant_literal('상시전투')}]"
)
_RE_ACCEPT = re.compile(rf"\[{whitespace_tolerant_literal('수락')}]")
_RE_DAILY_QUEST_START = re.compile(rf"\[{whitespace_tolerant_literal('의뢰')}]")
_RE_INVESTIGATION_START = re.compile(rf"\[{whitespace_tolerant_literal('상시조사')}]")
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


def _persist_battle_log(
    state: "BotState",
    battle_log: Optional[log_sheets.BattleCommandLog],
    reply_ref: str,
) -> None:
    """커맨드 정산 결과를 로그_전투에 기록하고, 필드 시트 스냅샷도 함께 갱신한다.

    스프레드시트 기록 실패가 전투 진행 자체를 막지 않도록 예외를 흡수한다.
    """
    if battle_log is None:
        return

    try:
        log_sheets.append_battle_log(
            state.spreadsheet,
            battle_log.field_id,
            battle_log.round_n,
            battle_log.phase,
            battle_log.command_text,
            battle_log.entries,
            reply_ref=reply_ref,
            error_trace=battle_log.error_trace,
        )

        if battle_log.is_main and state.session is not None:
            log_sheets.upsert_field_row(
                state.spreadsheet,
                battle_log.field_id,
                is_main=True,
                round_n=state.session.round_n,
                phase=state.session.current_phase.value,
                characters=log_sheets.build_field_characters(
                    state.session.context, include_hp=False
                ),
            )
        elif not battle_log.is_main and state.practice is not None:
            phase = state.practice.phase
            log_sheets.upsert_field_row(
                state.spreadsheet,
                battle_log.field_id,
                is_main=False,
                round_n=state.practice.round_n,
                phase=phase.value if phase is not None else "",
                characters=log_sheets.build_field_characters(
                    state.practice.context, include_hp=True
                ),
            )
    except Exception:
        logger.exception("전투 로그 기록 실패 (field_id=%s)", battle_log.field_id)


def _persist_noncombat_log(
    state: "BotState",
    log_info: Optional[log_sheets.NoncombatLogInfo],
    reply_ref: str,
) -> None:
    if log_info is None:
        return
    try:
        log_sheets.append_noncombat_log(
            state.spreadsheet,
            log_info.command_text,
            dice_roll=log_info.dice_roll,
            result=log_info.result,
            error_trace=log_info.error_trace,
            reply_ref=reply_ref,
        )
    except Exception:
        logger.exception("비전투 로그 기록 실패")


@dataclass
class BotState:
    char_dict: dict[str, CombatCharacterDataFromSpreadsheet]  # mastodon_id → data
    name_dict: dict[str, CombatCharacterDataFromSpreadsheet]  # name → data
    noncombat_char_dict: dict[
        str, NoncombatCharacterDataFromSpreadsheet
    ]  # mastodon_id → data
    spreadsheet: gspread.Spreadsheet
    session: Optional[BattleSession] = None
    preparation_status_id: Optional[int] = None  # [전투 준비] 안내 게시물 ID
    active_phase_post_id: Optional[int] = None  # 현재 페이즈 공지 게시물 ID
    pending_participants: list[str] = field(default_factory=list)  # mastodon_ids
    pending_placements: list[tuple] = field(
        default_factory=list
    )  # (name, faction, column)
    practice: Optional[PracticeBattleState] = None
    noncombat: NonCombatState = field(default_factory=NonCombatState)


def reload_char_data(state: BotState) -> None:
    """'캐릭터' 시트를 새로 읽어 state의 캐릭터 관련 캐시를 갱신한다.

    캐릭터 명단은 세션 도중에도 바뀔 수 있으므로(참전 신청, 수정 중인 행 등),
    캐릭터 관련 커맨드가 들어올 때마다(멘션 수신 시) 매번 새로 읽는다.
    """
    char_dict, name_dict, noncombat_char_dict = load_char_data(state.spreadsheet)
    state.char_dict = char_dict
    state.name_dict = name_dict
    state.noncombat_char_dict = noncombat_char_dict


class MastodonBotListener(StreamListener):
    def __init__(self, mastodon: Mastodon, state: BotState, bot_acct: str) -> None:
        super().__init__()
        self._mastodon = mastodon
        self._state = state
        self._bot_acct = bot_acct

    def on_notification(self, notification: dict) -> None:
        acct: Optional[str] = None
        status_id: Optional[int] = None
        try:
            if notification["type"] != "mention":
                return

            account = notification["account"]
            status = notification["status"]
            acct = account["acct"]
            status_id = status["id"]
            in_reply_to_id: Optional[int] = status.get("in_reply_to_id")

            command_text = _extract_command(status["content"])
            if not command_text:
                return

            reload_char_data(self._state)

            mentions = [
                m["acct"]
                for m in status.get("mentions", [])
                if m["acct"] != self._bot_acct
            ]
            self.__dispatch(
                acct, status_id, in_reply_to_id, command_text, status["visibility"], mentions
            )
        except Exception:
            logger.exception(
                "멘션 처리 중 오류 (acct=%s, status_id=%s)", acct, status_id
            )

    def __dispatch(
        self,
        acct: str,
        status_id: int,
        in_reply_to_id: Optional[int],
        text: str,
        visibility: str,
        mentions: list[str] | None = None,
    ) -> None:
        state = self._state

        # 1. admin 직접 멘션 또는 [상시전투] self-mention bypass → admin 커맨드
        is_admin = acct == ADMIN_MASTODON_ID
        is_investigation_self_mention = acct == self._bot_acct and bool(
            _RE_INVESTIGATION_BATTLE_SELF.search(text)
        )
        if is_admin or is_investigation_self_mention:
            result: AdminCommandResult = handle_admin_command(
                text, state, mentions=mentions or []
            )

            if not result.reply_text:
                # reply_text가 비어 있으면 game_post_text를 단일 답글로 전송
                if result.game_post_text is not None:
                    post = self._reply(
                        status_id, acct, visibility, result.game_post_text
                    )
                    new_post_id = post["id"]
                    if result.set_practice_prep_from_game_post and state.practice is not None:
                        state.practice.prep_post_id = new_post_id
                    if result.set_practice_active_post and state.practice is not None:
                        state.practice.active_post_id = new_post_id
                    if state.session is not None and state.session.started:
                        state.active_phase_post_id = (
                            new_post_id
                            if state.session.current_phase in _COMMAND_PHASES
                            else None
                        )
            else:
                # reply_text가 있는 경우: 답글 전송
                reply_status = self._reply(
                    status_id, acct, visibility, result.reply_text
                )
                _persist_battle_log(
                    state, result.battle_log, str(reply_status["id"])
                )

                if result.set_preparation_post:
                    state.preparation_status_id = reply_status["id"]

                # 퍼블릭 게시물 게시 (페이즈 게시물)
                if result.game_post_text is not None:
                    new_post = self._mastodon.status_post(
                        _truncate(result.game_post_text),
                        visibility="public",
                    )
                    new_post_id = new_post["id"]

                    if result.set_practice_prep_from_game_post and state.practice is not None:
                        state.practice.prep_post_id = new_post_id

                    if result.set_practice_active_post and state.practice is not None:
                        state.practice.active_post_id = new_post_id

                    if state.session is not None and state.session.started:
                        state.active_phase_post_id = (
                            new_post_id
                            if state.session.current_phase in _COMMAND_PHASES
                            else None
                        )

            return

        # 2. 대련/상시전투 준비 게시물 답글 (포지션 선언)
        if (
            state.practice is not None
            and state.practice.prep_post_id != 0
            and in_reply_to_id == state.practice.prep_post_id
        ):
            ps = state.practice
            if ps.is_investigation:
                # 상시전투: [아군/N열] 포지션 선언
                m = _RE_INVESTIGATION_DECLARATION.search(text)
                if m and acct in ps.expected_accts:
                    col_n = int(m.group(1))
                    try:
                        column = BattlefieldColumnIndex.from_str(f"{col_n}열")
                        ps.declared[acct] = (SideType.SIDE_1, column)
                        logger.info("상시전투 포지션 선언: %s → 아군 %s", acct, column)
                        if ps.all_declared():
                            game_post_text = _start_investigation_battle(state)
                            ps.prep_post_id = 0
                            new_post = self._mastodon.status_post(
                                _truncate(game_post_text), visibility="public"
                            )
                            if state.practice is not None:
                                state.practice.active_post_id = new_post["id"]
                    except ValueError:
                        pass
            else:
                # 대련: [N팀/N열] 포지션 선언
                m = _RE_DECLARATION.search(text)
                if m and acct in ps.expected_accts:
                    side_n = int(m.group(1))
                    col_n = int(m.group(2))
                    side = SideType.SIDE_1 if side_n == 1 else SideType.SIDE_2
                    try:
                        column = BattlefieldColumnIndex.from_str(f"{col_n}열")
                        ps.declared[acct] = (side, column)
                        logger.info(
                            "대련 포지션 선언: %s → %s %s", acct, side.value, column
                        )
                        if ps.all_declared() and ps.teams_valid():
                            game_post_text = _start_practice_battle(state)
                            ps.prep_post_id = 0
                            new_post = self._mastodon.status_post(
                                _truncate(game_post_text), visibility="public"
                            )
                            if state.practice is not None:
                                state.practice.active_post_id = new_post["id"]
                    except ValueError:
                        pass
            return

        # 3. 대련/상시전투 진행 중 커맨드 (practice active post 답글)
        if (
            state.practice is not None
            and state.practice.active_post_id is not None
            and in_reply_to_id == state.practice.active_post_id
        ):
            reply, game_post, battle_log = _handle_practice_command(
                acct, text, state
            )
            reply_status = self._reply(status_id, acct, visibility, reply)
            _persist_battle_log(state, battle_log, str(reply_status["id"]))
            if game_post is not None:
                new_post = self._mastodon.status_post(
                    _truncate(game_post), visibility="public"
                )
                if state.practice is not None:
                    state.practice.active_post_id = new_post["id"]
            return

        # 4. 전투 준비 참전 신청 (bot 준비 게시물에 대한 답글)
        if (
            state.preparation_status_id is not None
            and in_reply_to_id == state.preparation_status_id
        ):
            if acct in state.char_dict and acct not in state.pending_participants:
                state.pending_participants.append(acct)
                logger.info("참전 신청: %s (%s)", acct, state.char_dict[acct].name)
            return

        # 5. 전투 중 캐릭터 커맨드 (active_phase_post_id에 대한 답글)
        if (
            state.active_phase_post_id is not None
            and in_reply_to_id == state.active_phase_post_id
        ):
            response, battle_log = handle_character_command(acct, text, state)
            reply_status = self._reply(status_id, acct, visibility, response)
            _persist_battle_log(state, battle_log, str(reply_status["id"]))
            return

        nc = state.noncombat

        # 6. 일일 의뢰 판정 답글 (봇이 의뢰를 알려준 포스트에 대한 답글)
        if (
            in_reply_to_id is not None
            and in_reply_to_id in nc.get_daily_quest_post_ids()
        ):
            stat_name = parse_stat_name(text)
            if stat_name:
                response = handle_daily_quest_roll(acct, stat_name, state)
                self._reply(status_id, acct, visibility, response)
            return

        # 7. 상시조사 메뉴 답글 (봇이 4개 선택지를 보낸 포스트에 대한 답글)
        if (
            in_reply_to_id is not None
            and in_reply_to_id in nc.get_investigation_menu_post_ids()
        ):
            menu_acct = nc.find_acct_by_investigation_menu_post(in_reply_to_id)
            if menu_acct == acct:
                venue_name = text.strip().strip("[]")
                response = handle_investigation_venue_choice(acct, venue_name, state)
                post = self._reply(status_id, acct, visibility, response)
                finalize_investigation_overview_post(acct, post["id"], state)
            return

        # 8. 상시조사 수락 답글 (의뢰 개요 포스트에 대한 [수락] 답글)
        if (
            in_reply_to_id is not None
            and in_reply_to_id in nc.get_investigation_overview_post_ids()
            and _RE_ACCEPT.search(text)
        ):
            response = handle_investigation_accept(acct, state, in_reply_to_id)
            self._reply(status_id, acct, visibility, response)
            return

        # 9. [판정/스탯] — 독립 판정 (어떤 맥락에서도 사용 가능)
        stat_name = parse_stat_name(text)
        if stat_name:
            response = handle_roll(acct, stat_name, state)
            self._reply(status_id, acct, visibility, response)
            return

        # 10. [의뢰] — 일일 의뢰 시작
        if _RE_DAILY_QUEST_START.search(text):
            response = handle_daily_quest_start(acct, state)
            post = self._reply(status_id, acct, visibility, response)
            finalize_daily_quest_mid(acct, post["id"], state)
            return

        # 11. [상시조사] — 상시조사 메뉴
        if _RE_INVESTIGATION_START.search(text):
            response = handle_investigation_start(acct, state)
            post = self._reply(status_id, acct, visibility, response)
            finalize_investigation_menu_post(acct, post["id"], state)
            return

        # 12. [사용/아이템(/대상)(/개수)] — 비전투 아이템 사용
        use_item_args = parse_use_item_args(text)
        if use_item_args:
            item_name, target_name, count = use_item_args
            response, log_info = handle_use_item(
                acct, item_name, target_name, count, state
            )
            reply_status = self._reply(status_id, acct, visibility, response)
            _persist_noncombat_log(state, log_info, str(reply_status["id"]))
            return

        # 13. [양도/아이템/대상(/개수)] — 비전투 아이템 양도
        transfer_item_args = parse_transfer_item_args(text)
        if transfer_item_args:
            item_name, target_name, count = transfer_item_args
            response, log_info = handle_transfer_item(
                acct, item_name, target_name, count, state
            )
            reply_status = self._reply(status_id, acct, visibility, response)
            _persist_noncombat_log(state, log_info, str(reply_status["id"]))
            return

    def _reply(
        self, in_reply_to_id: int, acct: str, visibility: str, text: str
    ) -> dict:
        return self._mastodon.status_post(
            f"@{acct} {_truncate(text)}",
            in_reply_to_id=in_reply_to_id,
            visibility=visibility,
        )


def _start_investigation_battle(state: "BotState") -> str:
    """상시전투 포지션 선언 완료 후 아군을 배치하고 첫 라운드 게시 문자열을 반환한다."""
    ps = state.practice
    errors: list[str] = []

    for acct, (side, column) in ps.declared.items():
        data = state.char_dict.get(acct)
        if data is None:
            errors.append(f"{acct}의 캐릭터를 찾을 수 없습니다.")
            continue
        try:
            ps.context.add_character(data, side, column)
        except CommandValidationError as e:
            errors.append(str(e))

    total = len(ps.context.characters)
    ps.round_limit = max(3, 1 + total)
    ps.start_round()

    mover_label = ps.side_label(ps.first_mover)
    game_post = (
        f"◊ 상시전투 시작\n"
        f"라운드 상한: {ps.round_limit}라운드\n\n"
        f"[{ps.round_n}라운드] 선공: {mover_label}\n"
        f"선공은 이 게시물에 답글로 커맨드를 입력해 주세요.\n\n"
        f"{ps.context}"
    )
    if errors:
        game_post += "\n\n⚠️ 오류:\n" + "\n".join(errors)
    return game_post


def _start_practice_battle(state: "BotState") -> str:
    """대련 포지션 선언 완료 후 전투를 시작하고 첫 라운드 게시 문자열을 반환한다."""
    ps = state.practice
    errors: list[str] = []

    for acct, (side, column) in ps.declared.items():
        data = state.char_dict.get(acct)
        if data is None:
            errors.append(f"{acct}의 캐릭터를 찾을 수 없습니다.")
            continue
        try:
            ps.context.add_character(data, side, column)
        except CommandValidationError as e:
            errors.append(str(e))

    total = len(ps.context.characters)
    ps.round_limit = max(3, 1 + total)
    ps.start_round()

    mover_label = ps.side_label(ps.first_mover)
    game_post = (
        f"◊ 대련 시작\n"
        f"라운드 상한: {ps.round_limit}라운드\n\n"
        f"[{ps.round_n}라운드] 선공: {mover_label}\n"
        f"선공은 이 게시물에 답글로 커맨드를 입력해 주세요.\n\n"
        f"{ps.context}"
    )
    if errors:
        game_post += "\n\n⚠️ 오류:\n" + "\n".join(errors)
    return game_post


def _handle_practice_command(
    acct: str, text: str, state: "BotState"
) -> tuple[str, Optional[str], Optional[log_sheets.BattleCommandLog]]:
    """
    대련/상시전투 중 캐릭터 커맨드를 처리한다.
    반환값: (reply_text, game_post_text_or_None, battle_log_or_None)
    """
    ps = state.practice
    if ps is None:
        return "◊ 진행 중인 대련/상시전투가 없습니다.", None, None

    if acct not in state.char_dict:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None, None

    char_data = state.char_dict[acct]
    char_id = CharacterId(char_data.name)

    if char_id not in ps.context.characters:
        return "◊ 해당 캐릭터는 현재 전장에 배치되지 않았습니다.", None, None

    current_phase = ps.phase
    if current_phase is None:
        return "◊ 커맨드를 입력할 수 있는 타이밍이 아닙니다.", None, None

    field_id = str(ps.prep_post_id)
    round_n = ps.round_n

    try:
        command = parse_character_command(char_id, text)
        if command is None:
            return (
                "◊ 커맨드 형식을 인식할 수 없습니다. 예: [공격/이름] 또는 [이동/3]",
                None,
                None,
            )
        result = ps.manager.process_command(command)
        entries = [
            entry
            for part_result in result.part_results
            for entry in part_result.log_entries
        ]
        battle_log = log_sheets.BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=current_phase.value,
            command_text=text,
            is_main=False,
            entries=entries,
        )
    except CommandValidationError as e:
        battle_log = log_sheets.BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=current_phase.value,
            command_text=text,
            is_main=False,
            error_trace=traceback.format_exc(),
        )
        return f"◊ {e}", None, battle_log

    hp1 = ps.total_hp_by_side(SideType.SIDE_1)
    hp2 = ps.total_hp_by_side(SideType.SIDE_2)
    battle_mode = "상시전투" if ps.is_investigation else "대련"

    if current_phase == PracticeRoundPhase.FIRST_MOVER_ACTION:
        if hp1 == 0 or hp2 == 0:
            ps.end_round()
            winner_label = ps.side_label(ps.winner())
            game_post = (
                f"◊ {battle_mode} 종료 ({ps.round_n}라운드)\n\n"
                f"승자: {winner_label}\n\n"
                f"{ps.context}"
            )
            state.practice = None
            return "◊ 전투가 종료되었습니다.", game_post, battle_log

        ps.advance_to_second_mover()
        second_label = ps.side_label(ps.second_mover)
        game_post = (
            f"◊ [{ps.round_n}라운드] 후공: {second_label}\n"
            f"후공은 이 게시물에 답글로 커맨드를 입력해 주세요.\n\n"
            f"{ps.context}"
        )
        return "◊ 커맨드 처리 완료", game_post, battle_log

    # SECOND_MOVER_ACTION
    ps.end_round()

    if hp1 == 0 or hp2 == 0 or ps.round_n >= ps.round_limit:
        winner_label = ps.side_label(ps.winner())
        game_post = (
            f"◊ {battle_mode} 종료 ({ps.round_n}라운드)\n\n"
            f"승자: {winner_label}\n\n"
            f"{ps.context}"
        )
        state.practice = None
        return "◊ 전투가 종료되었습니다.", game_post, battle_log

    ps.start_round()
    mover_label = ps.side_label(ps.first_mover)
    game_post = (
        f"◊ [{ps.round_n}라운드] 선공: {mover_label}\n"
        f"선공은 이 게시물에 답글로 커맨드를 입력해 주세요.\n\n"
        f"{ps.context}"
    )
    return "◊ 커맨드 처리 완료", game_post, battle_log


def main() -> None:
    # 버프/스킬/패시브/아이템/인벤토리는 여기서 로드해도 바로 stale해지므로 쓰지 않는다.
    # 전투 세션(본 전투/대련/상시전투) 시작 시점에 load_battle_data()로 다시 로드한다.
    (
        _buff_dict,
        _skill_dict,
        _passive_skill_dict,
        _item_dict,
        _inventory,
        char_dict,
        name_dict,
        noncombat_char_dict,
        spreadsheet,
    ) = load_all_data()
    state = BotState(
        char_dict=char_dict,
        name_dict=name_dict,
        noncombat_char_dict=noncombat_char_dict,
        spreadsheet=spreadsheet,
    )

    mastodon = Mastodon(
        access_token=os.environ["MASTODON_ACCESS_TOKEN"],
        api_base_url=os.environ["MASTODON_API_BASE_URL"],
    )

    me = mastodon.me()
    logger.info("봇 시작: @%s", me["acct"])
    logger.info("등록된 캐릭터: %d명", len(char_dict))

    mastodon.stream_user(MastodonBotListener(mastodon, state, me["acct"]))


if __name__ == "__main__":
    main()
