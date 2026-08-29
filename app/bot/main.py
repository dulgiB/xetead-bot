import logging
import os
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

import gspread
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import count_bracket_groups, parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import BattlefieldColumnIndex
from battle.objects.models import CharacterId
from battle.practice.define import PracticeRoundPhase, SideType
from dotenv import load_dotenv
from mastodon import Mastodon, StreamListener
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet
from utils.name_matching import whitespace_tolerant_literal

from bot.battle_reply_text import (
    format_battle_end_log_entries,
    format_battle_reply,
    format_eliminated_characters,
)
from bot.commands import admin as admin_commands
from bot.commands.admin import AdminCommandResult, handle_admin_command
from bot.commands.character import handle_character_command
from bot.commands.noncombat import (
    finalize_daily_quest_mid,
    finalize_investigation_menu_post,
    finalize_investigation_overview_post,
    handle_1d100,
    handle_bag,
    handle_daily_quest_roll,
    handle_daily_quest_start,
    handle_investigation_accept,
    handle_investigation_decline,
    handle_investigation_menu_idle_reply,
    handle_investigation_start,
    handle_investigation_venue_choice,
    handle_roll,
    handle_transfer_item,
    handle_use_item,
    parse_bare_item_command,
    parse_stat_name,
    parse_transfer_item_args,
)
from bot import field_restore, log_sheets
from bot.dm_battle_state import DmBattleState
from bot.field_sheet_image import capture_field_sheet_image
from bot.load_data import load_all_data, load_char_data
from bot.noncombat_state import DailyQuestMidState, NonCombatState
from bot.practice_state import PracticeBattleState
from bot.session import BattleSession
from bot.sheet_cache import SheetCache

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# admin의 mastodon acct 값 (로컬 계정: "username", 리모트: "username@domain")
ADMIN_MASTODON_ID: str = os.environ["ADMIN_MASTODON_ID"]
# 상시전투에서 에너미 등을 대신 조작하는 세계관 서술 담당 계정. [상시전투]
# 개시와 상시전투 참가자 대상 프록시 커맨드에 한해 admin과 동등하게
# 허용된다(그 외 admin 커맨드 권한은 없다).
WORLD_MASTODON_ID: str = os.environ["WORLD_MASTODON_ID"]

_RE_MENTION = re.compile(r"@\S+")
# 팀/열 번호를 [12]/[1-7]로 제한하지 않고 느슨하게 캡처한다 — 범위를 벗어난
# 입력(예: [3팀/9열])도 일단 매칭시켜야 아래에서 명시적으로 검증하고 오류
# 답글을 보낼 수 있다. 엄격하게 제한하면 형식이 살짝 어긋난 입력은 매칭
# 자체가 안 돼 완전히 무시되어(무응답) 사용자가 재시도할 방법을 알 수 없다.
_RE_DECLARATION = re.compile(
    rf"\[([^\[\]/]+){whitespace_tolerant_literal('팀')}\s*/\s*([^\[\]]+)]"
)
_RE_INVESTIGATION_DECLARATION = re.compile(
    rf"\[{whitespace_tolerant_literal('아군')}\s*/\s*([^\[\]]+)]"
)
_RE_PRACTICE_RETIRE = re.compile(rf"\[{whitespace_tolerant_literal('탈락')}]")
_RE_INVESTIGATION_BATTLE_SELF = re.compile(
    rf"\[{whitespace_tolerant_literal('상시전투')}]"
)
_RE_ACCEPT = re.compile(rf"\[{whitespace_tolerant_literal('수락')}]")
_RE_DAILY_QUEST_START = re.compile(rf"\[{whitespace_tolerant_literal('의뢰')}]")
_RE_INVESTIGATION_START = re.compile(rf"\[{whitespace_tolerant_literal('상시조사')}]")
_RE_BAG = re.compile(rf"\[{whitespace_tolerant_literal('가방')}]")
_RE_1D100 = re.compile(r"\[\s*1\s*d\s*100\s*]", re.IGNORECASE)
_MAX_POST_LENGTH = 500

# 커맨드를 수신하는 페이즈 (active_phase_post_id 설정 대상)
_COMMAND_PHASES = {
    RoundPhaseType.ENEMY_PRE_ACTION,
    RoundPhaseType.ALLY_ACTION,
}


class _TextExtractor(HTMLParser):
    """Mastodon 포스트의 HTML 콘텐츠에서 평문을 추출한다.

    `<p>`/`<br>` 등 블록 경계에서 줄바꿈을 넣지 않으면 여러 문단이 그대로
    이어붙어 "묘사 문단\n\n◊ 커맨드" 같은 여러 줄짜리 입력이 한 줄로
    뭉개진다 — 프록시 커맨드는 줄 단위로 매칭되므로(여러 개를 한 메시지에
    함께 실을 수 있다) 문단 구분이 plain text에도 살아있어야 한다."""

    _BLOCK_TAGS = {"p", "br", "div"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

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


def _split_for_post(text: str, prefix_len: int) -> list[str]:
    """`text`를 `prefix_len`(매 게시물에 붙는 멘션 등 고정 접두어 길이)을
    감안해 `_MAX_POST_LENGTH` 이내의 여러 조각으로 나눈다. 계산식이 길어져도
    truncate로 뒤가 잘려나가지 않도록, 줄 단위로 묶다가 한도를 넘기 직전에
    새 조각을 시작한다. 한 줄 자체가 한도를 넘으면(예: 매우 긴 계산식 한
    줄) 그 줄만 강제로 다시 분할한다."""
    limit = max(1, _MAX_POST_LENGTH - prefix_len)
    lines = text.split("\n")
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks or [""]


def _practice_battle_type(ps: PracticeBattleState) -> log_sheets.FieldBattleType:
    return (
        log_sheets.FieldBattleType.INVESTIGATION
        if ps.is_investigation
        else log_sheets.FieldBattleType.PRACTICE
    )


def _practice_field_meta(ps: PracticeBattleState) -> dict:
    return {
        "prep_post_id": ps.prep_post_id,
        "active_post_id": ps.active_post_id,
        "visibility": ps.visibility,
        "round_limit": ps.round_limit,
        "first_mover": ps.first_mover.value if ps.first_mover else None,
        "second_mover": ps.second_mover.value if ps.second_mover else None,
    }


def _upsert_practice_field_row(
    state: "BotState", ps: PracticeBattleState, *, phase_value: str, ended: bool = False
) -> None:
    """대련/상시전투 라운드 시작/종료처럼 캐릭터 커맨드 없이 "필드" 행을
    직접 갱신해야 하는 지점에서 쓴다(평상시 커맨드별 갱신은
    `_persist_battle_log`가 담당). `phase_value`를 직접 받는 이유는, 라운드
    종료 시점엔 `ps.phase`가 이미 None(`PracticeRoundManager.end_round()`가
    비운 뒤)이라 호출측이 전환 전에 붙잡아 둔 값을 넘겨야 하기 때문이다."""
    try:
        log_sheets.upsert_field_row(
            state.spreadsheet,
            ps.field_id,
            battle_type=_practice_battle_type(ps),
            round_n=ps.round_n,
            phase=phase_value,
            characters=log_sheets.build_field_characters(ps.context, include_hp=True),
            ended=ended,
            meta=_practice_field_meta(ps),
            cache=state.sheet_cache,
        )
    except Exception:
        logger.exception("필드 시트 저장 실패 (대련/상시전투 field_id=%s)", ps.field_id)


def _register_practice(
    state: "BotState", ps: PracticeBattleState, new_post_id: int, *, prep: bool
) -> None:
    """PracticeBattleState의 진행 게시물(tip) 키를 new_post_id로 옮긴다.

    state.practices는 진행 게시물 id(prep 단계엔 prep_post_id, 시작 후엔
    active_post_id)를 키로 쓰므로, _register_dm_battle과 동일한 이유로 옛
    키를 먼저 지우지 않으면 이전 게시물 id로도 계속 라우팅되는 좀비 항목이
    남는다.
    """
    old_key = (
        ps.active_post_id
        if ps.active_post_id is not None
        else (ps.prep_post_id or None)
    )
    if old_key is not None:
        state.practices.pop(old_key, None)
    if prep:
        ps.prep_post_id = new_post_id
    else:
        ps.prep_post_id = 0
        ps.active_post_id = new_post_id
    state.practices[new_post_id] = ps


def _update_practice_field_active_post(
    state: "BotState", ps: PracticeBattleState
) -> None:
    """대련/상시전투 진행 게시물(active_post_id)이 바뀔 때마다 "필드" 시트
    메타에 반영한다 — upsert_field_row 호출 시점엔 아직 새 게시물 id가
    정해지지 않은 경우가 많아(게시 완료 후에야 알 수 있음), 게시가 끝난
    직후 별도로 패치한다."""
    try:
        log_sheets.update_field_meta(
            state.spreadsheet,
            ps.field_id,
            {"active_post_id": ps.active_post_id},
            cache=state.sheet_cache,
        )
    except Exception:
        logger.exception("필드 메타 갱신 실패 (대련/상시전투 field_id=%s)", ps.field_id)


def _apply_game_post_side_effects(
    state: "BotState", result: AdminCommandResult, new_post_id: int
) -> None:
    """game_post_text가 실제로 게시된 후, 그 post_id를 필요한 상태에 반영한다.

    reply_text 유무에 따라 게시 방식(첨부 미디어/가시성/답글 대상 등)은
    다르지만, 게시가 끝난 뒤 post_id를 어디에 반영할지는 두 경로에서 항상
    동일하므로 공용 헬퍼로 뽑았다.
    """
    if (
        result.set_practice_prep_from_game_post
        and result.practice_to_register is not None
    ):
        _register_practice(state, result.practice_to_register, new_post_id, prep=True)
    if result.dm_battle_to_register is not None:
        _register_dm_battle(state, result.dm_battle_to_register, new_post_id)
    if state.session is not None and state.session.started:
        state.active_phase_post_id = (
            new_post_id if state.session.current_phase in _COMMAND_PHASES else None
        )
        if state.preparation_status_id is not None:
            try:
                log_sheets.update_field_meta(
                    state.spreadsheet,
                    str(state.preparation_status_id),
                    {"active_phase_post_id": state.active_phase_post_id},
                    cache=state.sheet_cache,
                )
            except Exception:
                logger.exception(
                    "필드 메타 갱신 실패 (본 전투 field_id=%s)",
                    state.preparation_status_id,
                )


def _register_dm_battle(state: "BotState", dm: DmBattleState, new_post_id: int) -> None:
    """DmBattleState의 스레드 tip을 new_post_id로 옮긴다.

    state.dm_battles는 tip post_id를 키로 쓰므로, 옛 키를 지우지 않으면
    페이즈가 넘어갈 때마다 이전 게시물 id로도 계속 라우팅되는 좀비 항목이
    남는다 — 반드시 옛 키를 먼저 지운 뒤 새 키로 등록해야 한다.
    """
    if not dm.field_id:
        dm.field_id = str(new_post_id)
    state.dm_battles.pop(dm.active_post_id, None)
    dm.active_post_id = new_post_id
    state.dm_battles[new_post_id] = dm

    # DM 전투는 여러 개가 동시에 진행될 수 있어 field_id별로 "필드" 행을
    # 따로 관리한다 — 최초 등록(전투 발생) 시 행을 만들고, 이후 페이즈
    # 전환마다(advance_phase/continue) 다시 호출되어 라운드/페이즈/캐릭터/
    # active_post_id를 최신 상태로 갱신한다.
    try:
        log_sheets.upsert_field_row(
            state.spreadsheet,
            dm.field_id,
            battle_type=log_sheets.FieldBattleType.DM,
            round_n=dm.session.round_n,
            phase=dm.session.current_phase.value,
            characters=log_sheets.build_field_characters(
                dm.session.context, include_hp=False
            ),
            meta={"active_post_id": dm.active_post_id, "visibility": dm.visibility},
            cache=state.sheet_cache,
        )
    except Exception:
        logger.exception("필드 시트 저장 실패 (DM 전투 field_id=%s)", dm.field_id)


def _persist_battle_log(
    state: "BotState",
    battle_log: Optional[log_sheets.BattleCommandLog],
    reply_ref: str,
) -> None:
    """커맨드 정산 결과를 로그_전투(내부 자동화 DB)에 기록한다.

    스프레드시트 기록 실패가 전투 진행 자체를 막지 않도록 예외를 흡수한다.
    """
    if battle_log is None:
        return

    try:
        log_sheets.append_battle_log(
            state.log_spreadsheet,
            battle_log.field_id,
            battle_log.round_n,
            battle_log.phase,
            battle_log.command_text,
            battle_log.entries,
            reply_ref=reply_ref,
            error_trace=battle_log.error_trace,
            mastodon_id=battle_log.mastodon_id,
            cache=state.log_sheet_cache,
        )

        if (
            battle_log.battle_type == log_sheets.FieldBattleType.MAIN
            and state.session is not None
        ):
            log_sheets.upsert_field_row(
                state.spreadsheet,
                battle_log.field_id,
                battle_type=log_sheets.FieldBattleType.MAIN,
                round_n=state.session.round_n,
                phase=state.session.current_phase.value,
                characters=log_sheets.build_field_characters(
                    state.session.context, include_hp=False
                ),
                meta={
                    "name": state.session.name,
                    "active_phase_post_id": state.active_phase_post_id,
                },
                cache=state.sheet_cache,
            )
        elif battle_log.battle_type in (
            log_sheets.FieldBattleType.PRACTICE,
            log_sheets.FieldBattleType.INVESTIGATION,
        ):
            ps = admin_commands.find_practice_by_field_id(state, battle_log.field_id)
            if ps is not None:
                phase = ps.phase
                log_sheets.upsert_field_row(
                    state.spreadsheet,
                    battle_log.field_id,
                    battle_type=battle_log.battle_type,
                    round_n=ps.round_n,
                    phase=phase.value if phase is not None else "",
                    characters=log_sheets.build_field_characters(
                        ps.context, include_hp=True
                    ),
                    meta=_practice_field_meta(ps),
                    cache=state.sheet_cache,
                )
        elif battle_log.battle_type == log_sheets.FieldBattleType.DM:
            dm = admin_commands.find_dm_battle_by_field_id(state, battle_log.field_id)
            if dm is not None:
                log_sheets.upsert_field_row(
                    state.spreadsheet,
                    battle_log.field_id,
                    battle_type=log_sheets.FieldBattleType.DM,
                    round_n=dm.session.round_n,
                    phase=dm.session.current_phase.value,
                    characters=log_sheets.build_field_characters(
                        dm.session.context, include_hp=False
                    ),
                    meta={
                        "active_post_id": dm.active_post_id,
                        "visibility": dm.visibility,
                    },
                    cache=state.sheet_cache,
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
            state.log_spreadsheet,
            log_info.command_text,
            dice_roll=log_info.dice_roll,
            result=log_info.result,
            error_trace=log_info.error_trace,
            reply_ref=reply_ref,
            cache=state.log_sheet_cache,
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
    field_spreadsheet: gspread.Spreadsheet
    log_spreadsheet: gspread.Spreadsheet
    session: Optional[BattleSession] = None
    preparation_status_id: Optional[int] = None  # [전투 준비] 안내 게시물 ID
    active_phase_post_id: Optional[int] = None  # 현재 페이즈 공지 게시물 ID
    pending_participants: list[str] = field(default_factory=list)  # mastodon_ids
    pending_placements: list[tuple] = field(
        default_factory=list
    )  # (name, faction, column)
    # key = 현재 진행 게시물 id (prep 단계엔 prep_post_id, 시작 후엔
    # active_post_id) — dm_battles와 동일한 패턴으로, 여러 대련/상시전투가
    # 동시에 진행될 수 있다.
    practices: dict[int, PracticeBattleState] = field(default_factory=dict)
    noncombat: NonCombatState = field(default_factory=NonCombatState)
    dm_battles: dict[int, DmBattleState] = field(
        default_factory=dict
    )  # key = 현재 스레드 tip 게시물 id
    # 멘션 하나(on_notification 한 번) 처리 범위에서만 유효한 읽기 캐시.
    # sheet_cache는 state.spreadsheet(캐릭터/에너미/필드 시트), field_sheet_cache는
    # state.field_spreadsheet(공개용 "필드" 시트, 별도 스프레드시트), log_sheet_cache는
    # state.log_spreadsheet("로그_전투"/"로그_비전투", 별도 스프레드시트) 대상이다 —
    # 셋 다 render/upsert/캡처가 매번 spreadsheet.worksheet(name)을 직접 부르면
    # 그때마다 전체 시트 메타데이터를 새로 읽어오므로(gspread에 이름별 캐싱이 없다)
    # 분리해서 캐싱한다. on_notification 시작마다 셋 다 새로 만들어 교체하므로,
    # 이전 멘션에서 읽은 값이 다음 멘션까지 새어나가지 않는다.
    sheet_cache: Optional[SheetCache] = None
    field_sheet_cache: Optional[SheetCache] = None
    log_sheet_cache: Optional[SheetCache] = None
    # 비전투 [아이템명/...] 인식용 아이템 id 캐시 — sheet_cache와 달리 멘션마다
    # 교체되지 않고 TTL(noncombat.get_cached_item_names)이 만료될 때까지 여러
    # 멘션에 걸쳐 재사용된다(브래킷이 있는 멘션마다 아이템 시트를 새로 읽지
    # 않기 위함).
    item_name_cache: Optional[frozenset[str]] = None
    item_name_cache_loaded_at: float = 0.0


def reload_char_data(state: BotState) -> None:
    """'캐릭터' 시트를 새로 읽어 state의 캐릭터 관련 캐시를 갱신한다.

    캐릭터 명단은 세션 도중에도 바뀔 수 있으므로(참전 신청, 수정 중인 행 등),
    캐릭터 관련 커맨드가 들어올 때마다(멘션 수신 시) 매번 새로 읽는다.
    """
    char_dict, name_dict, noncombat_char_dict = load_char_data(
        state.spreadsheet, cache=state.sheet_cache
    )
    state.char_dict = char_dict
    state.name_dict = name_dict
    state.noncombat_char_dict = noncombat_char_dict


_STREAM_WATCHDOG_CHECK_INTERVAL_SEC = 20
_STREAM_WATCHDOG_STALE_THRESHOLD_SEC = 60


class MastodonBotListener(StreamListener):
    def __init__(self, mastodon: Mastodon, state: BotState, bot_acct: str) -> None:
        super().__init__()
        self._mastodon = mastodon
        self._state = state
        self._bot_acct = bot_acct
        self._last_event_at = time.monotonic()

    def on_abort(self, err: Exception) -> None:
        """스트리밍 연결이 끊어졌을 때 호출된다(재연결 직전마다 반복 호출됨).
        run_async=True + reconnect_async=True로 실행 중이면 라이브러리가
        백그라운드 스레드 안에서 알아서 재연결을 재시도하므로 여기서는
        가시성을 위해 로그만 남긴다 — 프로세스는 죽지 않는다."""
        logger.warning("스트리밍 연결이 끊어져 재연결을 시도합니다: %s", err)

    def handle_heartbeat(self) -> None:
        """서버가 15초 간격으로 보내는 하트비트(':thump', mastodon/streaming/
        index.js). watchdog()이 silent hang을 판단하는 기준 시각이라, 실제
        이벤트가 뜸해도 하트비트만 계속 오면 여기서 계속 갱신된다."""
        self._last_event_at = time.monotonic()

    def on_any_event(self, name: str, data=None, for_stream=None) -> None:
        """실제 이벤트(멘션 등) 수신 시각도 watchdog 기준에 반영한다."""
        self._last_event_at = time.monotonic()

    def watchdog(self, handle) -> None:
        """연결이 예외 없이 응답만 멎는 silent hang을 감지해 강제 재연결시킨다.

        `on_abort`는 라이브러리가 연결 종료를 예외로 감지했을 때만 불린다.
        그런데 리버스 프록시의 idle 타임아웃 등으로 TCP 연결 자체는 살아있는
        채 서버 응답(하트비트 포함)만 완전히 멎는 경우, requests의 read
        timeout(기본 300초)에만 기대면 재연결이 걸리지 않을 수 있다 — 실제로
        정상적인 새 알림이 서버에 도착했는데도 봇이 30분 넘게 아무것도 처리
        못한 채 멈춰 있던 장애가 있었다. 하트비트 최종 수신 시각을 직접
        추적해 임계값을 넘기면 현재 연결을 강제로 닫아, 라이브러리의 기존
        reconnect_async 경로(on_abort → 백그라운드 재연결)를 타게 만든다."""
        while handle.is_alive():
            time.sleep(_STREAM_WATCHDOG_CHECK_INTERVAL_SEC)
            idle_sec = time.monotonic() - self._last_event_at
            if idle_sec < _STREAM_WATCHDOG_STALE_THRESHOLD_SEC:
                continue
            logger.warning(
                "스트리밍 워치독: %.0f초간 하트비트/이벤트가 없어 연결을 강제로 "
                "끊고 재연결을 유도합니다",
                idle_sec,
            )
            connection = getattr(handle, "connection", None)
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    logger.exception("스트리밍 워치독: 연결 강제 종료 실패")
            self._last_event_at = time.monotonic()

    def _capture_field_media_ids(self, state: "BotState") -> list:
        """공개 필드 시트를 이미지로 캡처해 업로드하고 media_id 리스트를 반환한다.

        캡처/업로드 실패는 예외를 흡수하고 빈 리스트를 반환한다 — 텍스트만
        게시되며, 이 실패가 전투 진행 자체를 막지 않는다.
        """
        try:
            with capture_field_sheet_image(
                state.field_spreadsheet, cache=state.field_sheet_cache
            ) as image_path:
                media = self._mastodon.media_post(
                    str(image_path), mime_type="image/png"
                )
                return [media["id"]]
        except Exception:
            logger.exception("공개 필드 시트 이미지 캡처/업로드 실패")
            return []

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

            # 이 멘션 하나를 처리하는 동안에만 유효한 읽기 캐시로 교체한다 —
            # 커맨드 간에는 공유하지 않아, 전투 중 스프레드시트를 실시간으로
            # 고쳐도 다음 멘션부터는 다시 최신 값을 읽는다.
            self._state.sheet_cache = SheetCache(self._state.spreadsheet)
            self._state.field_sheet_cache = SheetCache(self._state.field_spreadsheet)
            self._state.log_sheet_cache = SheetCache(self._state.log_spreadsheet)

            reload_char_data(self._state)

            mentions = [
                m["acct"]
                for m in status.get("mentions", [])
                if m["acct"] != self._bot_acct
            ]
            # acct/status_id는 위에서 이미 무조건 대입됐다 — 선언 시점의
            # Optional은 이 지점 이전에 예외가 나 except로 빠졌을 때 로그에
            # None을 안전하게 쓰기 위한 것일 뿐, 여기 도달했다면 항상 채워져
            # 있다.
            assert acct is not None
            assert status_id is not None
            self.__dispatch(
                acct,
                status_id,
                in_reply_to_id,
                command_text,
                status["visibility"],
                mentions,
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

        is_admin = acct == ADMIN_MASTODON_ID
        is_world = acct == WORLD_MASTODON_ID

        # 0. 대련/상시전투 중 프록시 커맨드 (계정이 없는 캐릭터, 주로
        # 에너미를 admin/world가 대신 입력) — 대상이 활성 대련/상시전투
        # 참가자면 아래 admin 커맨드 라우팅보다 먼저 처리해, 캐릭터 본인
        # 답글과 동일하게 처리 직후 자동으로 다음 페이즈/라운드로 넘어가게
        # 한다. world는 상시전투 참가자만 대상으로 허용한다
        # (require_investigation=True) — 대련은 참가자 전원이 실제
        # 계정이라 world가 대신 입력할 이유가 없다.
        if is_admin or is_world:
            (
                proxy_reply,
                proxy_calc,
                proxy_game_post,
                proxy_battle_log,
                proxy_ended,
                proxy_ps,
            ) = _handle_practice_proxy_command(
                text, state, acct, require_investigation=not is_admin
            )
            if proxy_ps is not None:
                assert proxy_reply is not None
                practice_participants = list(proxy_ps.expected_accts)
                practice_visibility = proxy_ps.visibility
                reply_status = self._reply_with_calc(
                    status_id, acct, visibility, proxy_reply, proxy_calc
                )
                _persist_battle_log(state, proxy_battle_log, str(reply_status["id"]))
                if proxy_game_post is not None:
                    mention_prefix = _practice_mention_prefix(practice_participants)
                    new_post = self._mastodon.status_post(
                        _truncate(f"{mention_prefix}{proxy_game_post}"),
                        visibility=practice_visibility,
                        in_reply_to_id=reply_status["id"],
                    )
                    if not proxy_ended:
                        _register_practice(state, proxy_ps, new_post["id"], prep=False)
                        _update_practice_field_active_post(state, proxy_ps)
                return
            # proxy_ps가 None이면(world라면 상시전투 포함) 어떤 활성 대련/
            # 상시전투 참가자도 대상이 아니라는 뜻 — 아래 기존 라우팅으로 넘어간다.

        # 1. admin 직접 멘션 또는 [상시전투] self-mention bypass → admin 커맨드
        is_investigation_self_mention = acct == self._bot_acct and bool(
            _RE_INVESTIGATION_BATTLE_SELF.search(text)
        )
        if is_admin or is_investigation_self_mention:
            result: AdminCommandResult = handle_admin_command(
                text,
                state,
                acct=acct,
                mentions=mentions or [],
                visibility=visibility,
                in_reply_to_id=in_reply_to_id,
            )
            self._post_admin_result(result, status_id, acct, visibility, state)
            return

        # 1.1. world 계정은 [상시전투] 개시만 admin과 동일하게 허용한다
        # (배치는 이 명령 안에 [배치/이름/적군 N열]로 함께 실어 처리된다).
        # 그 외 admin 전용 커맨드([전투준비] 등)에는 접근할 수 없다.
        if is_world and admin_commands._RE_INVESTIGATION_BATTLE.search(text):
            result = admin_commands._cmd_investigation_battle(
                text, mentions or [], state, visibility
            )
            self._post_admin_result(result, status_id, acct, visibility, state)
            return

        # 1.5. 캐릭터 계정이 직접 [대련]을 시작 — 대련은 (상시전투와 달리)
        # Admin 커맨드가 아니라 캐릭터 전용 커맨드다. 발신 캐릭터 자신과
        # 함께 멘션된 상대가 참여 대상이 된다.
        if acct in state.char_dict and admin_commands._RE_PRACTICE_PREP.search(text):
            expected_accts = [acct] + [m for m in (mentions or []) if m != acct]
            result = admin_commands._cmd_practice_prep(
                expected_accts, state, visibility
            )
            self._post_admin_result(result, status_id, acct, visibility, state)
            return

        # 2. 대련/상시전투 준비 게시물 답글 (포지션 선언)
        practice = (
            state.practices.get(in_reply_to_id) if in_reply_to_id is not None else None
        )
        if practice is not None and practice.prep_post_id != 0:
            ps = practice
            if ps.is_investigation:
                # 상시전투: [아군/N열] 포지션 선언
                m = _RE_INVESTIGATION_DECLARATION.search(text)
                if m and acct in ps.expected_accts:
                    col_str = m.group(1).strip()
                    try:
                        column = BattlefieldColumnIndex.from_str(col_str)
                    except ValueError:
                        self._reply(
                            status_id,
                            acct,
                            visibility,
                            f"◊ 입력된 열({col_str})을 인식할 수 없습니다. '1' 등 "
                            "숫자만 입력하거나, '2열' 등 '○열' 형식을 사용해 "
                            "주세요. 예: [아군/2열]",
                        )
                        return
                    ps.declared[acct] = (SideType.SIDE_1, column)
                    logger.info("상시전투 포지션 선언: %s → 아군 %s", acct, column)
                    if ps.all_declared():
                        game_post_text = _start_investigation_battle(state, ps)
                        mention_prefix = _practice_mention_prefix(ps.expected_accts)
                        new_post = self._mastodon.status_post(
                            _truncate(f"{mention_prefix}{game_post_text}"),
                            visibility=ps.visibility,
                            in_reply_to_id=ps.prep_post_id,
                        )
                        _register_practice(state, ps, new_post["id"], prep=False)
                        _update_practice_field_active_post(state, ps)
            else:
                # 대련: [N팀/N열] 포지션 선언
                m = _RE_DECLARATION.search(text)
                if m and acct in ps.expected_accts:
                    side_str = m.group(1).strip()
                    if side_str not in ("1", "2"):
                        self._reply(
                            status_id,
                            acct,
                            visibility,
                            f"◊ 입력된 팀 번호({side_str})를 인식할 수 없습니다. "
                            "1팀 또는 2팀만 사용할 수 있습니다. 예: [1팀/2열]",
                        )
                        return
                    side = SideType.SIDE_1 if side_str == "1" else SideType.SIDE_2

                    col_str = m.group(2).strip()
                    try:
                        column = BattlefieldColumnIndex.from_str(col_str)
                    except ValueError:
                        self._reply(
                            status_id,
                            acct,
                            visibility,
                            f"◊ 입력된 열({col_str})을 인식할 수 없습니다. '1' 등 "
                            "숫자만 입력하거나, '2열' 등 '○열' 형식을 사용해 "
                            "주세요. 예: [1팀/2열]",
                        )
                        return

                    ps.declared[acct] = (side, column)
                    logger.info(
                        "대련 포지션 선언: %s → %s %s", acct, side.value, column
                    )
                    if ps.all_declared() and ps.teams_valid():
                        game_post_text = _start_practice_battle(state, ps)
                        mention_prefix = _practice_mention_prefix(ps.expected_accts)
                        new_post = self._mastodon.status_post(
                            _truncate(f"{mention_prefix}{game_post_text}"),
                            visibility=ps.visibility,
                            in_reply_to_id=ps.prep_post_id,
                        )
                        _register_practice(state, ps, new_post["id"], prep=False)
                        _update_practice_field_active_post(state, ps)
            return

        # 3. 대련/상시전투 진행 중 커맨드 (practice active post 답글)
        if practice is not None and practice.active_post_id is not None:
            ps = practice
            practice_visibility = ps.visibility
            # 정산 게시물(game_post)에 참여자 전원을 멘션하려면 호출 전에
            # 미리 담아둬야 한다 — 전투가 이번 커맨드로 종료되면 ended=True로
            # 알려준다.
            practice_participants = list(ps.expected_accts)
            reply, calc_text, game_post, battle_log, ended = _handle_practice_command(
                acct, text, state, ps
            )
            if reply is None:
                # 대괄호 커맨드 자체가 없는 답글(사담 등) — 조용히 무시한다.
                # 스레드는 active_post_id에 그대로 남아, 이후 정상 커맨드가
                # 오면 문제없이 이어진다.
                return
            reply_status = self._reply_with_calc(
                status_id, acct, visibility, reply, calc_text
            )
            _persist_battle_log(state, battle_log, str(reply_status["id"]))
            if game_post is not None:
                # 캐릭터의 커맨드 답글(reply_status) 바로 다음에 이어 붙여야
                # 스레드가 갈라지지 않는다 — 예전 라운드 공지(active_post_id,
                # 이 캐릭터 커맨드의 in_reply_to_id였던 게시물)에 다시 답글로
                # 달면, 캐릭터의 커맨드 답글과 다음 라운드 공지가 같은 부모의
                # 형제 게시물이 되어 스레드가 두 갈래로 갈라진다.
                # 정산(라운드 전환/종료) 게시물은 바로 위 답글 작성자만
                # 자동으로 알림을 받으므로, 대련/상시전투 참여자 전원이
                # 알림을 받도록 멘션을 명시적으로 붙인다.
                mention_prefix = _practice_mention_prefix(practice_participants)
                new_post = self._mastodon.status_post(
                    _truncate(f"{mention_prefix}{game_post}"),
                    visibility=practice_visibility,
                    in_reply_to_id=reply_status["id"],
                )
                if not ended:
                    _register_practice(state, ps, new_post["id"], prep=False)
                    _update_practice_field_active_post(state, ps)
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
            # active_phase_post_id는 session이 있을 때만 설정되고 전투 종료 시
            # session과 함께 None으로 리셋된다(admin.py 참고) — 항상 같이 산다.
            assert state.session is not None
            response, calc_text, battle_log = handle_character_command(
                acct,
                text,
                state,
                state.session,
                str(state.preparation_status_id),
                log_sheets.FieldBattleType.MAIN,
            )
            # silent_on_unrecognized를 안 넘겼으므로(기본값 False) response는
            # 항상 str이다 — 본 전투는 페이즈마다 게시물이 바뀌는 구조라
            # 사담을 조용히 무시하는 대상이 아니다.
            assert response is not None
            reply_status = self._reply_with_calc(
                status_id, acct, visibility, response, calc_text
            )
            _persist_battle_log(state, battle_log, str(reply_status["id"]))
            return

        # 5.5. DM 전투 중 캐릭터 커맨드 (해당 스레드의 tip 게시물에 대한 답글)
        if in_reply_to_id is not None and in_reply_to_id in state.dm_battles:
            dm_state = state.dm_battles[in_reply_to_id]
            reply, calc_text, end_post_text, end_post_calc_text, battle_log = (
                _handle_dm_battle_command(acct, text, state, dm_state)
            )
            if reply is None:
                # 대괄호 커맨드 자체가 없는 답글(사담 등) — 조용히 무시한다.
                return
            reply_status = self._reply_with_calc(
                status_id, acct, visibility, reply, calc_text
            )
            _persist_battle_log(state, battle_log, str(reply_status["id"]))
            if end_post_text is not None:
                end_post = self._mastodon.status_post(
                    _truncate(end_post_text),
                    visibility=dm_state.visibility,
                    in_reply_to_id=dm_state.active_post_id,
                )
                self._post_calc_followups(
                    end_post["id"],
                    dm_state.visibility,
                    end_post_calc_text,
                    admin_commands._dm_mention_prefix(dm_state),
                )
            return

        nc = state.noncombat

        # 6. 일일 의뢰 판정 답글 (봇이 의뢰를 알려준 포스트에 대한 답글)
        if (
            in_reply_to_id is not None
            and in_reply_to_id in nc.get_daily_quest_post_ids()
        ):
            stat_name = parse_stat_name(text)
            if stat_name:
                response, log_info = handle_daily_quest_roll(acct, stat_name, state)
                reply_status = self._reply(status_id, acct, visibility, response)
                _persist_noncombat_log(state, log_info, str(reply_status["id"]))
            return

        # 7. 상시조사 메뉴 답글 (봇이 4개 선택지를 보낸 포스트에 대한 답글)
        if (
            in_reply_to_id is not None
            and in_reply_to_id in nc.get_investigation_menu_post_ids()
        ):
            menu_acct = nc.find_acct_by_investigation_menu_post(in_reply_to_id)
            if menu_acct == acct:
                if count_bracket_groups(text) >= 1:
                    venue_name = text.strip().strip("[]")
                    response, log_info = handle_investigation_venue_choice(
                        acct, venue_name, state
                    )
                    post = self._reply(status_id, acct, visibility, response)
                    _persist_noncombat_log(state, log_info, str(post["id"]))
                    finalize_investigation_overview_post(acct, post["id"], state)
                else:
                    # 대괄호 커맨드 자체가 없는 답글(사담 등) — 장소를 정하지
                    # 않고 자율적으로 둘러본 것으로 안내하고 world를 태그한다.
                    response, log_info = handle_investigation_menu_idle_reply()
                    post = self._reply(status_id, acct, visibility, response)
                    _persist_noncombat_log(state, log_info, str(post["id"]))
            # menu_acct != acct(타인의 메뉴 게시물)이면 조용히 무시한다.
            return

        # 8. 상시조사 수락 답글 (의뢰 개요 포스트에 대한 [수락] 답글)
        if (
            in_reply_to_id is not None
            and in_reply_to_id in nc.get_investigation_overview_post_ids()
            and _RE_ACCEPT.search(text)
        ):
            response, log_info = handle_investigation_accept(
                acct, mentions or [], state, in_reply_to_id
            )
            expected_accts = [acct] + [m for m in (mentions or []) if m != acct]
            reply_status = self._reply(
                status_id, acct, visibility, response, mention_accts=expected_accts
            )
            _persist_noncombat_log(state, log_info, str(reply_status["id"]))
            return

        # 9. [판정/스탯] — 독립 판정 (어떤 맥락에서도 사용 가능)
        stat_name = parse_stat_name(text)
        if stat_name:
            response, log_info = handle_roll(acct, stat_name, state)
            reply_status = self._reply(status_id, acct, visibility, response)
            _persist_noncombat_log(state, log_info, str(reply_status["id"]))
            return

        # 10. [의뢰] — 일일 의뢰 시작
        if _RE_DAILY_QUEST_START.search(text):
            response, log_info = handle_daily_quest_start(acct, state)
            post = self._reply(status_id, acct, visibility, response)
            _persist_noncombat_log(state, log_info, str(post["id"]))
            finalize_daily_quest_mid(acct, post["id"], state)
            return

        # 11. [상시조사] — 상시조사 메뉴
        if _RE_INVESTIGATION_START.search(text):
            response, log_info = handle_investigation_start(acct, state)
            post = self._reply(status_id, acct, visibility, response)
            _persist_noncombat_log(state, log_info, str(post["id"]))
            finalize_investigation_menu_post(acct, post["id"], state)
            return

        # 12. [아이템명(/대상)(/개수)] — 비전투 아이템 사용. 전투 중과 동일하게
        # "사용/" 같은 접두어 없이 아이템명으로 바로 시작하며, 등록된
        # 아이템명과 일치할 때만 인식한다(위의 다른 커맨드 키워드와 아이템명이
        # 겹치지 않는다는 전제) — 그래서 다른 키워드 커맨드를 모두 확인한
        # 뒤, 최후순위로 검사한다.
        bare_item_args = parse_bare_item_command(text, state)
        if bare_item_args:
            item_name, target_name, count = bare_item_args
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

        # 14. [가방] — 소지금/아이템 확인 (어떤 맥락에서도 사용 가능)
        if _RE_BAG.search(text):
            response, log_info = handle_bag(acct, state)
            reply_status = self._reply(status_id, acct, visibility, response)
            _persist_noncombat_log(state, log_info, str(reply_status["id"]))
            return

        # 14.5. [1D100] — 독립 굴림 (대소문자 무관, 어떤 맥락에서도 사용 가능)
        if _RE_1D100.search(text):
            response, log_info = handle_1d100(acct, state)
            reply_status = self._reply(status_id, acct, visibility, response)
            _persist_noncombat_log(state, log_info, str(reply_status["id"]))
            return

        # 15. 의뢰 개요 포스트에 대한 그 외의 답글 ([수락]도 아니고 위의 다른
        # 커맨드에도 매칭되지 않음) — 의뢰를 받지 않고 떠난 것으로 안내
        if (
            in_reply_to_id is not None
            and in_reply_to_id in nc.get_investigation_overview_post_ids()
        ):
            response, log_info = handle_investigation_decline(
                acct, state, in_reply_to_id
            )
            reply_status = self._reply(status_id, acct, visibility, response)
            _persist_noncombat_log(state, log_info, str(reply_status["id"]))
            return

    def _post_admin_result(
        self,
        result: AdminCommandResult,
        status_id: int,
        acct: str,
        visibility: str,
        state: "BotState",
    ) -> None:
        """AdminCommandResult를 실제 게시물로 발행한다.

        Admin 커맨드(handle_admin_command)뿐 아니라, 캐릭터가 직접 시작하는
        [대련]처럼 같은 AdminCommandResult 셰이프를 반환하는 다른 진입점에서도
        재사용한다."""
        if not result.reply_text:
            # reply_text가 비어 있으면 game_post_text를 단일 답글로 전송
            if result.game_post_text is not None:
                post = self._reply(status_id, acct, visibility, result.game_post_text)
                _apply_game_post_side_effects(state, result, post["id"])
        else:
            # reply_text가 있는 경우: 답글 전송 (텍스트만 — 필드 시트
            # 이미지는 페이즈 게시물에만 첨부한다). post_as_new_status면
            # 답글이 아니라 타임라인의 새 게시물로 올린다(전투 준비 공지 등).
            if result.post_as_new_status:
                reply_status = self._mastodon.status_post(
                    _truncate(result.reply_text), visibility="public"
                )
            else:
                reply_status = self._reply_with_calc(
                    status_id,
                    acct,
                    visibility,
                    result.reply_text,
                    result.calc_text,
                )
            _persist_battle_log(state, result.battle_log, str(reply_status["id"]))
            for extra_log in result.battle_logs:
                _persist_battle_log(state, extra_log, str(reply_status["id"]))

            if result.set_preparation_post:
                state.preparation_status_id = reply_status["id"]

            # 퍼블릭 게시물 게시 (페이즈 게시물) — 필드 시트 이미지를
            # 첨부한다 (render_public_field_sheet는 admin.py의 각
            # 핸들러에서 이미 호출됐으므로 여기서는 캡처만).
            if result.game_post_text is not None:
                game_media_ids = (
                    self._capture_field_media_ids(state)
                    if result.attach_field_image
                    else []
                )
                post_text = result.game_post_text
                # 이미지 캡처가 실패하면(빈 media_ids) 필드 현황을 텍스트로
                # 대체 표시한다 — 성공 시에는 이미지만으로 충분하므로
                # str(context) 보드를 중복으로 붙이지 않는다.
                if (
                    result.attach_field_image
                    and not game_media_ids
                    and state.session is not None
                ):
                    post_text = f"{post_text}\n\n{state.session.context}"
                base_kwargs: dict = {}
                if result.game_post_visibility is not None:
                    base_kwargs["visibility"] = result.game_post_visibility
                # 적군 행동 정산처럼 캐릭터 수가 많아지면 post_text 자체가
                # 500자를 넘을 수 있다 — truncate로 뒷부분을 잘라내지 않고,
                # 계산식(_post_calc_followups)과 동일하게 줄 단위로 나눈
                # 여러 게시물을 스레드로 이어 보낸다.
                chunks = _split_for_post(post_text, 0)
                first_kwargs = dict(base_kwargs, media_ids=game_media_ids or None)
                if result.game_post_reply_to_confirmation:
                    # 이전 페이즈 공지(admin의 [진행] 요청이 답글로 달렸던
                    # 그 게시물)에 다시 답글로 달면, 방금 위에서 보낸
                    # 확인 답글(reply_status)과 이 게시물이 같은 부모의
                    # 형제가 되어 스레드가 갈라진다 — 확인 답글 뒤에
                    # 이어야 [이전 공지] ← [admin 요청] ← [확인 답글] ←
                    # [이 공지] 순으로 선형으로 이어진다.
                    first_kwargs["in_reply_to_id"] = reply_status["id"]
                new_post = self._mastodon.status_post(chunks[0], **first_kwargs)
                for chunk in chunks[1:]:
                    new_post = self._mastodon.status_post(
                        chunk, in_reply_to_id=new_post["id"], **base_kwargs
                    )
                _apply_game_post_side_effects(state, result, new_post["id"])
                self._post_calc_followups(
                    new_post["id"],
                    result.game_post_visibility,
                    result.game_post_calc_text,
                    result.game_post_calc_prefix,
                )

        if result.admin_dm_text:
            # 플레이어에게 공개되는 reply_text/game_post_text와는 완전히
            # 별개로, admin에게만 조용히 알려야 하는 내용(스프레드시트 설정
            # 오류 등)을 DM으로 보낸다 — 재기동 복원 안내(main() 하단)와
            # 동일한 스타일.
            try:
                self._mastodon.status_post(
                    f"@{ADMIN_MASTODON_ID} {result.admin_dm_text}",
                    visibility="direct",
                )
            except Exception:
                logger.exception("admin DM 전송 실패")

    def _reply(
        self,
        in_reply_to_id: int,
        acct: str,
        visibility: str,
        text: str,
        media_ids: Optional[list] = None,
        mention_accts: Optional[list[str]] = None,
    ) -> dict:
        """답글을 보낸다. 계산식이 길어 한 게시물 길이 한도를 넘으면
        truncate로 뒷부분을 잘라내지 않고, 줄 단위로 나눈 여러 게시물을
        서로 답글로 이어붙인 스레드로 보낸다. 반환값은 그 스레드의 마지막
        게시물 status dict — 이 답글에 이어지는 후속 게시물(다음 라운드
        공지 등)이 스레드 맨 끝에 달리게 하기 위함이다.

        mention_accts를 주면 발신자(acct) 한 명 대신 그 목록 전원을 앞에
        멘션한다 (대련/DM 전투의 참여자 전원 멘션과 동일한 목적 — 여러
        캐릭터가 함께 엮인 결과를 모두에게 알려야 할 때 사용)."""
        mention_prefix = (
            " ".join(f"@{a}" for a in mention_accts) + " "
            if mention_accts
            else f"@{acct} "
        )
        chunks = _split_for_post(text, len(mention_prefix))
        status = self._mastodon.status_post(
            f"{mention_prefix}{chunks[0]}",
            in_reply_to_id=in_reply_to_id,
            visibility=visibility,
            media_ids=media_ids or None,
        )
        for chunk in chunks[1:]:
            status = self._mastodon.status_post(
                f"{mention_prefix}{chunk}",
                in_reply_to_id=status["id"],
                visibility=visibility,
            )
        return status

    def _reply_with_calc(
        self,
        in_reply_to_id: int,
        acct: str,
        visibility: str,
        text: str,
        calc_text: str,
        media_ids: Optional[list] = None,
    ) -> dict:
        """계산식(calc_text)이 없으면 평범한 답글 하나만 보낸다.

        있으면 게시물을 둘로 나누는 대신, CW(content warning) 게시물 하나로
        합쳐 보낸다 — 본문(text, 결과 요약)은 spoiler_text로 넣어 항상 바로
        보이게 하고, 계산식은 그 게시물의 (접었다 펴는) 본문으로 넣는다.
        Mastodon의 글자수 제한은 spoiler_text와 본문 길이를 합산해서
        적용되므로, 계산식이 길어 한 게시물에 안 들어가면 truncate하지
        않고 spoiler_text에 "(1/2)"처럼 번호를 매긴 여러 게시물로 나눠
        순서대로 이어 보낸다. 반환값은 그 스레드의 첫 게시물 status dict다
        — 다음 게시물이 스레드를 이어가려면 이 게시물에 답글로 달려야
        하기 때문이다.

        멘션(@계정)은 spoiler_text에 넣어도 실제 멘션으로 파싱되지 않아
        상대방에게 알림이 가지 않으므로, 반드시 본문(계산식) 쪽에 넣는다.

        `spoiler_text`는 실측 결과 본문(status)과 별개로 그 자체가 500자
        한도를 갖는다(합산 500자 제한과는 별도). DM 전투처럼 매 답글에
        필드 보드 텍스트가 덧붙어 `text`가 그 자체로 500자를 넘어가면
        한 게시물로 합칠 수 없으므로, 그 경우엔 본문을 평범한 답글로
        먼저 보내고 계산식만 별도의 CW 후속 게시물로 이어 붙인다."""
        if not calc_text:
            return self._reply(in_reply_to_id, acct, visibility, text, media_ids)

        if len(text) > _MAX_POST_LENGTH:
            return self._reply_then_calc_followup(
                in_reply_to_id, acct, visibility, text, calc_text, media_ids
            )

        mention_prefix = f"@{acct} "
        # spoiler_text에 번호 접미사(" (N/N)")가 붙을 수 있으므로, 먼저
        # 접미사 없이 나눠 조각 수를 가늠한 뒤 필요하면 그 접미사 길이만큼
        # 예산을 줄여 다시 나눈다.
        provisional_chunks = _split_for_post(calc_text, len(mention_prefix) + len(text))
        if len(provisional_chunks) > 1:
            suffix_len = len(f" ({len(provisional_chunks)}/{len(provisional_chunks)})")
            calc_chunks = _split_for_post(
                calc_text, len(mention_prefix) + len(text) + suffix_len
            )
        else:
            calc_chunks = provisional_chunks

        multiple = len(calc_chunks) > 1

        def _spoiler(i: int) -> str:
            return f"{text} ({i}/{len(calc_chunks)})" if multiple else text

        first_status = self._mastodon.status_post(
            f"{mention_prefix}{calc_chunks[0]}",
            in_reply_to_id=in_reply_to_id,
            visibility=visibility,
            media_ids=media_ids or None,
            spoiler_text=_spoiler(1),
        )
        reply_to = first_status["id"]
        for i, chunk in enumerate(calc_chunks[1:], start=2):
            calc_status = self._mastodon.status_post(
                f"{mention_prefix}{chunk}",
                in_reply_to_id=reply_to,
                visibility=visibility,
                spoiler_text=_spoiler(i),
            )
            reply_to = calc_status["id"]
        return first_status

    def _reply_then_calc_followup(
        self,
        in_reply_to_id: int,
        acct: str,
        visibility: str,
        text: str,
        calc_text: str,
        media_ids: Optional[list] = None,
    ) -> dict:
        """`_reply_with_calc`의 폴백: 본문(text)이 그 자체로 spoiler_text
        한도(500자)를 넘어 한 게시물로 합칠 수 없을 때, 본문을 평범한 답글로
        먼저 보내고 계산식을 별도의 CW(spoiler_text="계산식") 후속
        게시물로 이어 붙인다. 반환값은 (CW 게시물이 아닌) 본문 답글의
        status dict다."""
        reply_status = self._reply(in_reply_to_id, acct, visibility, text, media_ids)
        self._post_calc_followups(
            reply_status["id"], visibility, calc_text, prefix=f"@{acct} "
        )
        return reply_status

    def _post_calc_followups(
        self,
        in_reply_to_id: int,
        visibility: Optional[str],
        calc_text: str,
        prefix: str = "",
    ) -> None:
        """계산식(calc_text)이 있으면 spoiler_text="계산식"을 붙인 CW
        게시물로 in_reply_to_id에 답글로 이어 보낸다. 계산식이 길어 한
        게시물에 안 들어가면 truncate하지 않고 "계산식(1)", "계산식(2)"...
        로 번호를 매긴 여러 게시물로 나눠 순서대로 이어 보낸다.

        `visibility`가 None이면(부모 게시물도 visibility를 명시하지 않고
        계정 기본값을 따르는 경우) 이 후속 게시물도 동일하게 visibility
        인자 자체를 생략해 계정 기본값을 따르게 한다.

        `prefix`는 매 조각 앞에 반복해서 붙일 고정 접두어다 — 개별 커맨드
        답글은 그 답글을 단 계정에게 알림이 가도록 "@계정\\n"을, DM
        전투(visibility="direct")는 멘션되지 않은 게시물이 참가자에게
        아예 보이지 않으므로 참가자 멘션을 반복해서 넘겨야 한다. 게임
        진행 공지(game_post)처럼 특정 수신자가 없는 경우는 빈 문자열이면
        된다."""
        if not calc_text:
            return
        calc_chunks = _split_for_post(calc_text, len(prefix))
        multiple = len(calc_chunks) > 1
        reply_to = in_reply_to_id
        for i, chunk in enumerate(calc_chunks, start=1):
            spoiler = f"계산식({i})" if multiple else "계산식"
            post_kwargs: dict = {"in_reply_to_id": reply_to, "spoiler_text": spoiler}
            if visibility is not None:
                post_kwargs["visibility"] = visibility
            calc_status = self._mastodon.status_post(f"{prefix}{chunk}", **post_kwargs)
            reply_to = calc_status["id"]


def _practice_mention_prefix(participants: list[str]) -> str:
    """대련/상시전투 참여자 멘션 텍스트를 만든다. 정산(라운드 전환/종료)
    게시물은 바로 위 답글(캐릭터 커맨드에 대한 봇의 응답)에 이어 붙는
    별도 게시물이라, 명시적으로 멘션하지 않으면 그 답글 작성자를 제외한
    나머지 참여자는 알림을 받지 못한다."""
    if not participants:
        return ""
    return " ".join(f"@{a}" for a in participants) + " "


def _field_text(ps: PracticeBattleState) -> str:
    """대련/상시전투 필드 상태 텍스트(위치 보드 + 버프/디버프 요약). 진행
    중인 전투 게시물에 쓴다 — 전투 종료 게시물에는 버프/디버프 요약이
    더 이상 의미가 없으므로 대신 _field_board()를 쓴다.

    상시전투는 side_label()이 이미 "아군"/"적군"을 쓰므로 그대로, 대련은
    "1팀"/"2팀"으로 진영 헤더가 바뀐다(본 전투용 BattlefieldContext.__str__
    기본값인 "아군"/"적군" 대신).

    상시전투는 본 전투 필드 이미지와 같은 순서(적군 먼저)를 유지하지만,
    대련은 "2팀"이 항상 먼저 출력되는 게 팀 번호 순서와 어긋나 헷갈리므로
    "1팀"이 먼저 출력되게 한다(ally_first) — SIDE_1↔FactionType 매핑
    자체는 그대로이므로 라벨-데이터 대응은 변하지 않는다."""
    return ps.context.format_field_text(
        ally_label=ps.side_label(SideType.SIDE_1),
        enemy_label=ps.side_label(SideType.SIDE_2),
        ally_first=not ps.is_investigation,
        compact_columns=True,
    )


def _field_board(ps: PracticeBattleState) -> str:
    """대련/상시전투 필드 위치 보드(버프/디버프 요약 제외). 전투 종료
    게시물처럼 남은 버프/디버프 목록이 더 이상 의미 없는 자리에 쓴다."""
    return ps.context.format_position_board(
        ally_label=ps.side_label(SideType.SIDE_1),
        enemy_label=ps.side_label(SideType.SIDE_2),
        ally_first=not ps.is_investigation,
        compact_columns=True,
    )


def _winner_roster_text(ps: PracticeBattleState, winner: Optional[SideType]) -> str:
    """승자 팀 명단을 "(이름1, 이름2)" 형식으로 반환한다. 승자가 없으면
    (동점) 빈 문자열."""
    if winner is None:
        return ""
    names = [char.id.name for char in ps.context.get_side_characters(winner)]
    if not names:
        return ""
    return f" ({', '.join(names)})"


def _apply_practice_battle_end_effects(ps: PracticeBattleState) -> str:
    """전투 종료 시점 버프 훅([재앙] 등, BuffBase.on_battle_end())을 처리하고,
    그 결과를 계산식과 함께 담은 텍스트 블록을 반환한다(발동한 효과가
    없으면 빈 문자열). **반드시 ps.winner() 호출보다 먼저 불러야 한다** —
    이 훅으로 바뀐 HP가 승패 판정에도 반영돼야 하기 때문이다."""
    battle_end_entries = ps.context.on_battle_end()
    body, _calc = format_battle_end_log_entries(ps.context, battle_end_entries)
    return body


def _start_investigation_battle(state: "BotState", ps: PracticeBattleState) -> str:
    """상시전투 포지션 선언 완료 후 아군을 배치하고 첫 라운드 게시 문자열을 반환한다."""
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
    ps.field_id = str(ps.prep_post_id)
    ps.start_round()
    _upsert_practice_field_row(
        state, ps, phase_value=ps.phase.value if ps.phase else ""
    )

    mover_label = ps.side_label(ps.first_mover)
    game_post = (
        f"◊ 상시전투 시작\n"
        f"라운드 상한: {ps.round_limit}라운드\n\n"
        f"[{ps.round_n}라운드] 선공: {mover_label}\n"
        f"선공은 타래로 이어서 커맨드를 입력해 주세요.\n\n"
        f"{_field_text(ps)}"
    )
    if errors:
        game_post += "\n\n⚠️ 오류:\n" + "\n".join(errors)
    return game_post


def _start_practice_battle(state: "BotState", ps: PracticeBattleState) -> str:
    """대련 포지션 선언 완료 후 전투를 시작하고 첫 라운드 게시 문자열을 반환한다."""
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
    ps.field_id = str(ps.prep_post_id)
    ps.start_round()
    _upsert_practice_field_row(
        state, ps, phase_value=ps.phase.value if ps.phase else ""
    )

    mover_label = ps.side_label(ps.first_mover)
    game_post = (
        f"◊ 대련 시작\n"
        f"라운드 상한: {ps.round_limit}라운드\n\n"
        f"[{ps.round_n}라운드] 선공: {mover_label}\n"
        f"선공은 타래로 이어서 커맨드를 입력해 주세요.\n\n"
        f"{_field_text(ps)}"
    )
    if errors:
        game_post += "\n\n⚠️ 오류:\n" + "\n".join(errors)
    return game_post


def _finalize_practice_phase(
    state: "BotState", ps: PracticeBattleState, current_phase: PracticeRoundPhase
) -> tuple[str, bool]:
    """대련/상시전투에서 커맨드 하나(캐릭터 본인 답글 또는 admin/world
    프록시)가 처리된 직후 호출한다 — 다음 페이즈/라운드로 전환하거나
    전투를 종료하고, 그 안내 게시물 텍스트를 만든다.

    캐릭터 본인 경로(_handle_practice_command)와 프록시 경로
    (_handle_practice_proxy_command)가 완전히 동일한 전환 로직을
    공유해야 한다 — 그렇지 않으면 계정이 없어 프록시로만 조작 가능한
    에너미가 마지막으로 행동하는 페이즈에서 라운드가 영원히 멈춘다.

    반환값: (game_post_text, ended). ended=True면 ps가 이미
    state.practices에서 제거된 상태다."""
    assert ps.active_post_id is not None  # 호출측이 이미 확인함
    battle_mode = "상시전투" if ps.is_investigation else "대련"

    if current_phase == PracticeRoundPhase.FIRST_MOVER_ACTION:
        hp1 = ps.total_hp_by_side(SideType.SIDE_1)
        hp2 = ps.total_hp_by_side(SideType.SIDE_2)
        if hp1 == 0 or hp2 == 0:
            ps.end_round()
            battle_end_body = _apply_practice_battle_end_effects(ps)
            winner = ps.winner()
            winner_label = ps.side_label(winner)
            body_blocks = [
                block for block in (_field_board(ps), battle_end_body) if block
            ]
            game_post = (
                f"◊ {battle_mode} 종료 ({ps.round_n}라운드)\n\n"
                f"승자: {winner_label}{_winner_roster_text(ps, winner)}\n\n"
                + "\n\n".join(body_blocks)
            )
            _upsert_practice_field_row(
                state, ps, phase_value=current_phase.value, ended=True
            )
            state.practices.pop(ps.active_post_id, None)
            return game_post, True

        ps.advance_to_second_mover()
        second_label = ps.side_label(ps.second_mover)
        game_post = (
            f"◊ [{ps.round_n}라운드] 후공: {second_label}\n"
            f"후공은 타래로 이어서 커맨드를 입력해 주세요.\n\n"
            f"{_field_text(ps)}"
        )
        return game_post, False

    # SECOND_MOVER_ACTION
    ps.end_round()
    # end_round()에서 ON_ROUND_END 버프(DoT/HoT)나 탈락 처리가 방금 일어날 수
    # 있으므로, hp1/hp2는 end_round() 이후에 다시 계산해야 한다 — 그 전에
    # 계산한 값을 그대로 쓰면 라운드 종료 시점에 발생한 전멸을 놓친다.
    hp1 = ps.total_hp_by_side(SideType.SIDE_1)
    hp2 = ps.total_hp_by_side(SideType.SIDE_2)

    if hp1 == 0 or hp2 == 0 or ps.round_n >= ps.round_limit:
        battle_end_body = _apply_practice_battle_end_effects(ps)
        winner = ps.winner()
        winner_label = ps.side_label(winner)
        body_blocks = [block for block in (_field_board(ps), battle_end_body) if block]
        game_post = (
            f"◊ {battle_mode} 종료 ({ps.round_n}라운드)\n\n"
            f"승자: {winner_label}{_winner_roster_text(ps, winner)}\n\n"
            + "\n\n".join(body_blocks)
        )
        _upsert_practice_field_row(
            state, ps, phase_value=current_phase.value, ended=True
        )
        state.practices.pop(ps.active_post_id, None)
        return game_post, True

    ps.start_round()
    mover_label = ps.side_label(ps.first_mover)
    game_post = (
        f"◊ [{ps.round_n}라운드] 선공: {mover_label}\n"
        f"선공은 타래로 이어서 커맨드를 입력해 주세요.\n\n"
        f"{_field_text(ps)}"
    )
    return game_post, False


def _handle_practice_proxy_command(
    text: str, state: "BotState", acct: str, *, require_investigation: bool
) -> tuple[
    Optional[str],
    str,
    Optional[str],
    Optional[log_sheets.BattleCommandLog],
    bool,
    Optional[PracticeBattleState],
]:
    """대련/상시전투 중 admin/world가 계정이 없는 캐릭터(주로 에너미)의
    커맨드를 프록시로 대신 입력한다. text에서 "(◊ )이름 [커맨드]" 패턴을
    모두 찾아, 그중 조건에 맞는 활성 대련/상시전투 참가자로 해석되는 첫
    번째 줄만 처리한다 — 대련/상시전투는 페이즈당 유효한 커맨드가 1개뿐이라
    여러 줄을 한꺼번에 처리할 이유가 없다.

    require_investigation이 True면(world 계정) 상시전투가 아닌 대련
    참가자는 대상에서 제외한다 — world는 상시전투 맥락에서만 프록시가
    허용된다.

    캐릭터 본인 답글 경로(_handle_practice_command)와 동일하게, 처리
    직후 _finalize_practice_phase로 자동으로 다음 페이즈/라운드로
    전환한다.

    반환값: (reply_text_or_None, calc_text, game_post_text_or_None,
    battle_log_or_None, ended, ps_or_None). ps가 None이면 이 text에서
    조건에 맞는 대상을 찾지 못했다는 뜻 — 호출측은 기존 admin 라우팅
    (본 전투 프록시 등)으로 넘어가야 한다."""
    for m in admin_commands._RE_PROXY.finditer(text):
        char_name, cmd_str = m.group(1).strip(), m.group(2).strip()
        ps: Optional[PracticeBattleState] = None
        char_id = None
        for candidate in state.practices.values():
            if candidate.active_post_id is None:
                continue
            if require_investigation and not candidate.is_investigation:
                continue
            resolved = candidate.context.resolve_character_id(CharacterId(char_name))
            if resolved in candidate.context.characters:
                ps, char_id = candidate, resolved
                break
        if ps is None or char_id is None:
            continue

        current_phase = ps.phase
        if current_phase is None:
            return (
                "◊ 커맨드를 입력할 수 있는 타이밍이 아닙니다.",
                "",
                None,
                None,
                False,
                ps,
            )

        field_id = ps.field_id
        round_n = ps.round_n

        try:
            command = parse_character_command(char_id, cmd_str, ps.context)
            if command is None:
                return "◊ 커맨드 형식을 인식할 수 없습니다.", "", None, None, False, ps
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
                battle_type=_practice_battle_type(ps),
                command_text=cmd_str,
                mastodon_id=acct,
                entries=entries,
            )
            reply_text, calc_text = format_battle_reply(
                ps.context, char_id, result.part_results
            )
        except CommandValidationError as e:
            battle_log = log_sheets.BattleCommandLog(
                field_id=field_id,
                round_n=round_n,
                phase=current_phase.value,
                battle_type=_practice_battle_type(ps),
                command_text=cmd_str,
                mastodon_id=acct,
                error_trace=traceback.format_exc(),
            )
            return f"◊ {e}", "", None, battle_log, False, ps

        game_post, ended = _finalize_practice_phase(state, ps, current_phase)
        return reply_text, calc_text, game_post, battle_log, ended, ps

    return None, "", None, None, False, None


def _handle_practice_command(
    acct: str, text: str, state: "BotState", ps: PracticeBattleState
) -> tuple[
    Optional[str], str, Optional[str], Optional[log_sheets.BattleCommandLog], bool
]:
    """
    대련/상시전투 중 캐릭터 커맨드를 처리한다.
    반환값: (reply_text_or_None, calc_text, game_post_text_or_None,
    battle_log_or_None, ended)

    reply_text가 None이면 대괄호 커맨드 자체가 없는 답글(사담 등)이었다는
    뜻이다 — 호출측은 아무 것도 게시하지 않고 조용히 무시해야 한다. calc_text가
    비어 있지 않으면 호출측이 spoiler_text="계산식" 후속 게시물로 이어 보낸다.
    ended가 True면 이 커맨드로 대련/상시전투가 종료되어 ps가 state.practices에서
    이미 제거되었다는 뜻이다 — 호출측은 game_post를 새 active_post_id로 다시
    등록하면 안 된다.
    """
    assert ps.active_post_id is not None  # 호출측이 이미 확인함

    if acct not in state.char_dict:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", "", None, None, False

    char_data = state.char_dict[acct]
    char_id = CharacterId(char_data.name)

    if char_id not in ps.context.characters:
        return "◊ 해당 캐릭터는 현재 전장에 배치되지 않았습니다.", "", None, None, False

    if _RE_PRACTICE_RETIRE.search(text):
        # 탈락은 턴 순서와 무관한 자진 기권 커맨드라, 선공/후공 페이즈
        # 검증(manager.process_command)을 거치지 않고 즉시 처리한다.
        side = ps.context.get_side(char_id)
        ps.context.remove_character(char_id)
        reply_text = format_eliminated_characters([char_id])
        battle_log = log_sheets.BattleCommandLog(
            field_id=ps.field_id,
            round_n=ps.round_n,
            phase=ps.phase.value if ps.phase is not None else "",
            battle_type=_practice_battle_type(ps),
            command_text=text,
            mastodon_id=acct,
        )

        if ps.total_hp_by_side(side) > 0:
            # 같은 편에 남은 캐릭터가 있으면 전투는 계속된다.
            return reply_text, "", None, battle_log, False

        battle_mode = "상시전투" if ps.is_investigation else "대련"
        battle_end_body = _apply_practice_battle_end_effects(ps)
        winner = ps.winner()
        winner_label = ps.side_label(winner)
        body_blocks = [block for block in (_field_board(ps), battle_end_body) if block]
        game_post = (
            f"◊ {battle_mode} 종료 ({ps.round_n}라운드)\n\n"
            f"승자: {winner_label}{_winner_roster_text(ps, winner)}\n\n"
            + "\n\n".join(body_blocks)
        )
        _upsert_practice_field_row(
            state,
            ps,
            phase_value=ps.phase.value if ps.phase is not None else "",
            ended=True,
        )
        state.practices.pop(ps.active_post_id, None)
        return reply_text, "", game_post, battle_log, True

    current_phase = ps.phase
    if current_phase is None:
        return "◊ 커맨드를 입력할 수 있는 타이밍이 아닙니다.", "", None, None, False

    field_id = ps.field_id
    round_n = ps.round_n

    if count_bracket_groups(text) >= 2:
        return (
            "◊ 한 메시지에는 대괄호 커맨드를 하나만 입력할 수 있습니다. "
            "여러 스킬/아이템을 한 번에 쓰려면 '[스킬A/대상 - 스킬B]'처럼 "
            "하이픈으로 이어서 한 대괄호 안에 작성해 주세요.",
            "",
            None,
            None,
            False,
        )

    try:
        command = parse_character_command(char_id, text, ps.context)
        if command is None:
            # 대괄호 커맨드가 아예 없는 답글(사담 등) — 에러 없이 무시한다.
            return None, "", None, None, False
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
            battle_type=_practice_battle_type(ps),
            command_text=text,
            mastodon_id=acct,
            entries=entries,
        )
        reply_text, calc_text = format_battle_reply(
            ps.context, char_id, result.part_results
        )
    except CommandValidationError as e:
        battle_log = log_sheets.BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=current_phase.value,
            battle_type=_practice_battle_type(ps),
            command_text=text,
            mastodon_id=acct,
            error_trace=traceback.format_exc(),
        )
        return f"◊ {e}", "", None, battle_log, False

    game_post, ended = _finalize_practice_phase(state, ps, current_phase)
    return reply_text, calc_text, game_post, battle_log, ended


def _handle_dm_battle_command(
    acct: str, text: str, state: "BotState", dm_state: DmBattleState
) -> tuple[
    Optional[str], str, Optional[str], str, Optional[log_sheets.BattleCommandLog]
]:
    """
    DM 전투 중 캐릭터 커맨드를 처리한다. handle_character_command를 그대로
    재사용하되, DM 전투는 스레드 답글이 유일한 실시간 확인 수단이므로 매
    답글에 현재 필드 상태(str(context))를 덧붙이고, 처리 후 전멸 여부를
    확인해 전멸 시 전투를 종료한다.

    반환값: (reply_text_or_None, calc_text, end_post_text_or_None,
    end_post_calc_text, battle_log_or_None)

    reply_text가 None이면 대괄호 커맨드 자체가 없는 답글(사담 등)이었다는
    뜻이다 — 호출측은 아무 것도 게시하지 않고 조용히 무시해야 한다. calc_text/
    end_post_calc_text가 비어 있지 않으면 호출측이 spoiler_text="계산식"
    후속 게시물로 이어 보낸다. DM 전투는 스레드 하나가 계속 이어지는
    구조라 대련/상시전투와 동일하게 처리한다(본 전투는 페이즈마다 게시물이
    바뀌므로 대상이 아니다).
    """
    response, calc_text, battle_log = handle_character_command(
        acct,
        text,
        state,
        dm_state.session,
        dm_state.field_id,
        log_sheets.FieldBattleType.DM,
        silent_on_unrecognized=True,
    )
    if response is None:
        return None, "", None, "", None
    response = f"{response}\n\n{dm_state.session.context}"

    winner = admin_commands._check_dm_battle_wipe(dm_state)
    if winner is None:
        return response, calc_text, None, "", battle_log

    end_body, end_calc = admin_commands._end_dm_battle(dm_state, state, winner)
    end_post_text = f"{admin_commands._dm_mention_prefix(dm_state)}{end_body}"
    return response, calc_text, end_post_text, end_calc, battle_log


def _restore_daily_quest_mid_state(state: "BotState") -> int:
    """캐릭터 시트의 daily_quest_status_id 컬럼을 읽어, 봇 재기동으로
    사라진 NonCombatState.daily_quest_mid를 복원한다(finalize_daily_quest_mid
    참고 — 의뢰 판정 대기 중일 때만 이 컬럼이 채워져 있다). 반환값은
    복원된 건수.

    bot_reply_post_id는 타입 힌트만 int일 뿐 실제로는(mastodon.py가 게시물
    ID를 MaybeSnowflakeIdType(str 서브클래스)로 다루므로) 코드베이스 어디서도
    진짜 int로 변환되지 않는다 — 다른 모든 경로는 항상 타입 힌트가 없는
    dict 접근(post["id"] 등, mypy가 Any로 취급)으로만 이 값을 다루기 때문에
    이 불일치가 지금까지 드러나지 않았을 뿐이다. 여기서 int()로 캐스팅하면
    라운드트립한 값이 실제 알림에서 오는 in_reply_to_id(str 서브클래스)와
    더 이상 같지 않아 매칭에 항상 실패한다 — 시트에서 읽은 문자열
    (daily_quest_status_id: str, 명시적으로 타입이 있어 Any로 가려지지
    않음)을 그대로 써야 한다."""
    restored = 0
    for acct, char_data in state.noncombat_char_dict.items():
        if not char_data.daily_quest_status_id:
            continue
        state.noncombat.daily_quest_mid[acct] = DailyQuestMidState(
            bot_reply_post_id=char_data.daily_quest_status_id  # type: ignore[arg-type]
        )
        restored += 1
    return restored


class _MarkdownMastodon(Mastodon):
    """봇 답글이 항상 마크다운으로 렌더링되도록 status_post()의 content_type
    기본값을 text/markdown으로 강제한다. Pleroma/Akkoma 계열이 아닌 인스턴스는
    이 파라미터를 무시하므로 안전하다."""

    def status_post(self, *args, **kwargs):
        kwargs.setdefault("content_type", "text/markdown")
        return super().status_post(*args, **kwargs)


def main() -> None:
    # 버프/스킬/패시브/아이템/인벤토리는 평상시엔 여기서 로드해도 바로
    # stale해지므로 쓰지 않고, 전투 세션(본 전투/DM 전투/대련/상시전투) 시작
    # 시점에 load_battle_data()로 다시 로드한다. 다만 재기동 직후 딱 한 번,
    # 아래 field_restore.restore_all()이 "필드" 시트에 남아 있던 미종료
    # 전투를 재구성할 때는 이 시점의 값이 곧 최신값이라 그대로 재사용한다.
    (
        buff_dict,
        skill_dict,
        passive_skill_dict,
        item_dict,
        inventory,
        char_dict,
        name_dict,
        noncombat_char_dict,
        spreadsheet,
        field_spreadsheet,
        log_spreadsheet,
    ) = load_all_data()
    state = BotState(
        char_dict=char_dict,
        name_dict=name_dict,
        noncombat_char_dict=noncombat_char_dict,
        spreadsheet=spreadsheet,
        field_spreadsheet=field_spreadsheet,
        log_spreadsheet=log_spreadsheet,
    )
    restored_daily_quest_count = _restore_daily_quest_mid_state(state)

    mastodon = _MarkdownMastodon(
        access_token=os.environ["MASTODON_ACCESS_TOKEN"],
        api_base_url=os.environ["MASTODON_API_BASE_URL"],
    )

    me = mastodon.me()
    logger.info("봇 시작: @%s", me["acct"])
    logger.info("등록된 캐릭터: %d명", len(char_dict))
    if restored_daily_quest_count:
        logger.info("일일 의뢰 진행 상태 복원: %d건", restored_daily_quest_count)

    try:
        restored_summaries = field_restore.restore_all(
            state, buff_dict, skill_dict, passive_skill_dict, item_dict, inventory
        )
    except Exception:
        logger.exception("전투 재기동 복원 중 오류가 발생했습니다")
        restored_summaries = []

    if restored_summaries:
        logger.info("재기동 복원: %d건", len(restored_summaries))
        summary_text = "\n".join(f"- {s}" for s in restored_summaries)
        try:
            mastodon.status_post(
                f"@{ADMIN_MASTODON_ID} ◊ 봇 재기동: 아래 전투를 이어서 진행합니다.\n{summary_text}",
                visibility="direct",
            )
        except Exception:
            logger.exception("재기동 복원 안내 DM 전송 실패")

    # run_async=True + reconnect_async=True: 스트리밍 연결이 끊어져도(네트워크
    # 순단 등) 라이브러리가 백그라운드 스레드 안에서 재연결만 재시도하고
    # 프로세스 자체는 죽지 않는다. 기본값(run_async=False)은 재연결 로직이
    # 전혀 없어 연결이 끊기는 즉시 예외가 여기까지 전파되어 프로세스가
    # 죽고 Docker의 restart:always로만 복구되는데, 그때마다 스프레드시트
    # 전체 재로드 + 미종료 전투 복원(field_restore.restore_all())을 다시
    # 거쳐야 해서 단순 네트워크 순단에도 매번 콜드 재시작이 발생했다.
    listener = MastodonBotListener(mastodon, state, me["acct"])
    handle = mastodon.stream_user(
        listener,
        run_async=True,
        reconnect_async=True,
    )
    watchdog_thread = threading.Thread(
        target=listener.watchdog, args=(handle,), daemon=True
    )
    watchdog_thread.start()
    while handle.is_alive():
        time.sleep(60)


if __name__ == "__main__":
    main()
