import logging
import random
import re
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import (
    BattleLogEntry,
    BattleLogEntryKind,
    CommandPartProcessResult,
)
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
)
from battle.objects.models import CharacterId
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import SideType
from battle.practice.round_manager import PracticeRoundManager
from utils.name_matching import resolve_matching_key, whitespace_tolerant_literal

from bot.battle_reply_text import (
    format_battle_end_log_entries,
    format_battle_reply,
    format_eliminated_characters,
    format_final_hp_roster,
    format_round_end_log_entries,
)
from bot.dm_battle_state import DmBattleState
from bot.field_sheet_renderer import render_public_field_sheet
from bot.load_data import load_battle_data, reveal_declared_enemy_skills
from bot.log_sheets import (
    BattleCommandLog,
    build_field_characters,
    upsert_field_row,
    write_back_changed_hp,
)
from bot.practice_state import PracticeBattleState
from bot.session import BattleSession

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from bot.main import BotState
    from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet

logger = logging.getLogger(__name__)

# 스프레드시트 저장/렌더링 등 내부 구현 detail을 담은 예외 메시지는
# 플레이어/관리자에게 그대로 노출하지 않는다 — 대신 이 문구로 통일해
# 보여주고, 전체 트레이스는 _log_system_error()로 서버 로그에만 남긴다.
_SYSTEM_ERROR_MESSAGE = "◊ 시스템 오류입니다."


def _log_system_error(action: str) -> None:
    """진행 중인 except 블록 안에서 호출해, action(예: '필드 시트 저장')이
    실패했다는 전체 트레이스를 서버 로그에 남긴다."""
    logger.exception("%s 실패", action)


_RE_BATTLE_PREP = re.compile(rf"\[{whitespace_tolerant_literal('전투준비')}]")
_RE_MANUAL_PLACE = re.compile(
    rf"\[{whitespace_tolerant_literal('배치')}\s*/\s*([^/\]]+?)\s*/\s*([^/\]]+)]"
)
_RE_BATTLE_START = re.compile(rf"\[{whitespace_tolerant_literal('전투개시')}]")
_RE_BATTLE_NAME = re.compile(r"「(.+?)」")
_RE_PHASE = re.compile(rf"\[{whitespace_tolerant_literal('진행')}]")
_RE_CONTINUE = re.compile(rf"\[{whitespace_tolerant_literal('전투속행')}]")
_RE_END = re.compile(rf"\[{whitespace_tolerant_literal('전투종료')}]")
_RE_INVESTIGATION_BATTLE = re.compile(rf"\[{whitespace_tolerant_literal('상시전투')}]")
_RE_PRACTICE_PREP = re.compile(rf"\[{whitespace_tolerant_literal('대련')}]")
_RE_DM_BATTLE_START = re.compile(rf"\[{whitespace_tolerant_literal('전투발생')}]")
_RE_PROXY = re.compile(r"^([^\[\]]+?)\s+(\[.+])$", re.DOTALL)


def _dm_mention_prefix(dm_state: "DmBattleState") -> str:
    """DM 전투 참가자 멘션 텍스트를 만든다. visibility="direct" 게시물은
    명시적으로 멘션된 계정만 볼 수 있으므로, 페이즈 전환/정산/종료 게시물마다
    이 프리픽스를 붙여야 참가자가 스레드를 계속 확인할 수 있다."""
    if not dm_state.mentions:
        return ""
    return " ".join(f"@{a}" for a in dm_state.mentions) + "\n"


_VALID_COLUMNS = [
    BattlefieldColumnIndex.COL1,
    BattlefieldColumnIndex.COL2,
    BattlefieldColumnIndex.COL3,
    BattlefieldColumnIndex.COL4,
    BattlefieldColumnIndex.COL5,
    BattlefieldColumnIndex.COL6,
    BattlefieldColumnIndex.COL7,
]


@dataclass
class AdminCommandResult:
    reply_text: str
    game_post_text: Optional[str] = None
    # True이면 reply 자체의 status_id를 preparation_status_id로 저장한다
    set_preparation_post: bool = False
    # True이면 game_post_text의 post_id를 practice.prep_post_id로 저장한다
    set_practice_prep_from_game_post: bool = False
    # True이면 game_post_text의 post_id를 practice.active_post_id로 저장한다
    set_practice_active_post: bool = False
    # 프록시 커맨드(_cmd_proxy)로 캐릭터 커맨드가 정산된 경우 로그_전투 기록용 자료
    battle_log: Optional[BattleCommandLog] = None
    # True이면 game_post_text 게시 시 공개 필드 시트 이미지를 첨부한다 (라운드 시작/종료)
    attach_field_image: bool = False
    # True이면 reply_text를 답글이 아니라 타임라인의 새 게시물로 올린다 (전투 준비 공지 등)
    post_as_new_status: bool = False
    # game_post_text가 게시된 후 그 post_id를 이 DmBattleState의 active_post_id로
    # 쓰고 state.dm_battles에 등록한다 (DM 전투 전용)
    dm_battle_to_register: Optional["DmBattleState"] = None
    # True이면 game_post_text를 admin에게 보낸 확인 답글(reply_text가 게시된
    # 바로 그 게시물) 뒤에 이어 붙인다 — 스레드가 [이전 라운드 공지] ←
    # [admin의 진행 요청] ← [확인 답글] ← [다음 라운드 공지]처럼 선형으로
    # 이어지게 하기 위함이다. 이전 라운드 공지(dm_state.active_post_id)에
    # 다시 답글로 달면 확인 답글과 다음 라운드 공지가 같은 부모의 형제
    # 게시물이 되어 스레드가 두 갈래로 갈라진다. False면 기존처럼 독립
    # 게시물로 게시한다 — 본 전투는 건드리지 않고 DM 전투만 사용.
    game_post_reply_to_confirmation: bool = False
    # game_post_text 게시 시 강제할 visibility. None이면 계정 기본값을 따른다
    # (DM 전투는 세션 내내 최초 개시 멘션의 visibility로 고정)
    game_post_visibility: Optional[str] = None


def handle_admin_command(
    text: str,
    state: "BotState",
    mentions: list[str] | None = None,
    visibility: str = "public",
    in_reply_to_id: Optional[int] = None,
) -> AdminCommandResult:
    """
    어드민 커맨드 텍스트를 파싱해 처리하고 AdminCommandResult를 반환한다.
    game_post_text가 None이 아니면 호출측에서 퍼블릭 게시물로 게시한다.
    """
    dm_state = (
        state.dm_battles.get(in_reply_to_id) if in_reply_to_id is not None else None
    )
    if dm_state is not None:
        if _RE_PHASE.search(text):
            return _cmd_dm_battle_advance_phase(dm_state, state)
        if _RE_CONTINUE.search(text):
            return _cmd_dm_battle_continue(dm_state, state)
        if _RE_END.search(text):
            return AdminCommandResult(_cmd_dm_battle_end(dm_state, state))
        if m := _RE_PROXY.match(text):
            char_name = m.group(1).strip()
            cmd_str = m.group(2).strip()
            reply_text, battle_log = _cmd_dm_battle_proxy(
                dm_state, char_name, cmd_str, state
            )
            return AdminCommandResult(reply_text, battle_log=battle_log)
        return AdminCommandResult(
            "◊ 전투 진행 중에는 [진행]/[전투속행]/[전투종료] 또는 "
            "'{캐릭터 이름} [커맨드]' 형식의 프록시 커맨드만 사용할 수 있습니다."
        )

    if _RE_BATTLE_PREP.search(text):
        return _cmd_battle_prep(state)

    if _RE_DM_BATTLE_START.search(text):
        return _cmd_dm_battle_start(text, mentions or [], state, visibility)

    # [상시전투]는 README에 문서화된 대로 같은 메시지에 [배치/이름/진영 열]을
    # 함께 실어 적을 즉시 배치할 수 있다(_cmd_investigation_battle이 내부에서
    # 그 [배치/...] 토큰을 직접 파싱한다) — 그래서 이 분기가 아래의 본 전투용
    # _RE_MANUAL_PLACE보다 먼저 와야 한다. 순서가 바뀌면 "[상시전투]
    # [배치/.../적군 4열]" 같은 정상 사용법이 본 전투용 수동 배치로 잘못
    # 라우팅되어 "진행 중인 전투가 없습니다" 오류로 실패한다(session이 아직
    # 없으므로).
    if _RE_INVESTIGATION_BATTLE.search(text):
        return _cmd_investigation_battle(text, mentions or [], state, visibility)

    if m := _RE_MANUAL_PLACE.search(text):
        name = m.group(1).strip()
        faction_col_str = m.group(2).strip()
        return AdminCommandResult(_cmd_manual_place(name, faction_col_str, state))

    if _RE_BATTLE_START.search(text):
        name_match = _RE_BATTLE_NAME.search(text)
        battle_name = name_match.group(1).strip() if name_match else None
        return _cmd_battle_start(state, battle_name)

    if _RE_PHASE.search(text):
        return _cmd_advance_phase(state)

    if _RE_CONTINUE.search(text):
        return _cmd_continue_battle(state)

    if _RE_END.search(text):
        return AdminCommandResult(_cmd_end(state))

    if m := _RE_PROXY.match(text):
        char_name = m.group(1).strip()
        cmd_str = m.group(2).strip()
        reply_text, battle_log = _cmd_proxy(char_name, cmd_str, state)
        return AdminCommandResult(reply_text, battle_log=battle_log)

    return AdminCommandResult("◊ 알 수 없는 관리자 커맨드입니다.")


# ---------------------------------------------------------------------------
# 개별 커맨드 핸들러
# ---------------------------------------------------------------------------


def _cmd_battle_prep(state: "BotState") -> AdminCommandResult:
    if state.session is not None:
        return AdminCommandResult("◊ 이미 진행 중인 전투가 있습니다.")

    (
        buff_dict,
        skill_dict,
        passive_skill_dict,
        item_dict,
        inventory,
        state.char_dict,
        state.name_dict,
        state.noncombat_char_dict,
    ) = load_battle_data(state.spreadsheet, cache=state.sheet_cache)
    state.session = BattleSession(
        buff_dict,
        skill_dict,
        passive_skill_dict,
        item_dict,
        inventory,
    )
    reply = "◊ 전투 준비\n\n참여를 희망하는 인원은 이곳에 답글을 남겨주세요."
    return AdminCommandResult(reply, set_preparation_post=True, post_as_new_status=True)


def _cmd_manual_place(name: str, faction_col_str: str, state: "BotState") -> str:
    if state.session is None:
        return "◊ 진행 중인 전투가 없습니다. 먼저 [전투 준비]를 입력하세요."
    if state.session.started:
        return "◊ 전투가 이미 시작되어 캐릭터를 배치할 수 없습니다."
    name = resolve_matching_key(name, state.name_dict.keys())
    if name not in state.name_dict:
        return f"◊ 지정된 캐릭터({name})를 찾을 수 없습니다."

    parts = faction_col_str.split()
    if len(parts) < 2:
        return "◊ 캐릭터 배치는 [배치/(캐릭터 이름)/(진영) 0열] 형식을 따라야 합니다. (예시: [배치/늑대/적군 3열])"

    faction_str = parts[0]
    col_str = parts[1]

    try:
        faction = FactionType(faction_str)
    except ValueError:
        return f"◊ 입력된 진영({faction_str})을 인식할 수 없습니다. 진영은 '아군' 또는 '적군'이어야 합니다."

    try:
        column = BattlefieldColumnIndex.from_str(col_str)
    except ValueError:
        return f"◊ 입력된 열({col_str})을 인식할 수 없습니다. '1' 등 숫자만 입력하거나, '2열' 등 '○열' 형식을 사용해 주세요."

    state.pending_placements.append((name, faction, column))
    return f"◊ {name}({faction.value} {column}열)을 수동 배치 목록에 추가했습니다."


def _cmd_battle_start(
    state: "BotState", battle_name: Optional[str] = None
) -> AdminCommandResult:
    if state.session is None:
        return AdminCommandResult(
            "◊ 진행 중인 전투가 없습니다. 먼저 [전투 준비]를 입력하세요."
        )
    if state.session.started:
        return AdminCommandResult("◊ 전투가 이미 시작되었습니다.")
    if not state.pending_participants and not state.pending_placements:
        return AdminCommandResult(
            "◊ 배치된 캐릭터가 없습니다. 참전 신청이나 [배치/...] 커맨드를 먼저 입력하세요."
        )

    # 1. 수동 배치 처리 (pending_placements)
    errors: list[str] = []
    for name, faction, column in state.pending_placements:
        data = state.name_dict.get(name)
        if data is None:
            errors.append(f"지정된 캐릭터({name})를 찾을 수 없습니다.")
            continue
        try:
            state.session.add_character(data, faction, column)
        except CommandValidationError as e:
            errors.append(str(e))

    # 2. 아군 랜덤 배치 (pending_participants)
    ally_data_list = [
        state.char_dict[acct]
        for acct in state.pending_participants
        if acct in state.char_dict
    ]
    errors.extend(
        _assign_random_positions(state.session, ally_data_list, FactionType.ALLY)
    )

    state.pending_placements.clear()
    state.pending_participants.clear()

    if not state.session.context.characters:
        reply_parts = ["◊ 배치에 모두 실패하여 전투를 시작하지 못했습니다."]
        if errors:
            reply_parts.append("⚠️ 오류:\n" + "\n".join(errors))
        return AdminCommandResult("\n".join(reply_parts))

    # 3. 전투 시작
    state.session.start()
    state.session.name = battle_name

    # 4. 필드 시트 저장
    system_error = False
    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            is_main=True,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            characters=build_field_characters(state.session.context, include_hp=False),
            cache=state.sheet_cache,
        )
    except Exception:
        _log_system_error("필드 시트 저장")
        system_error = True

    try:
        render_public_field_sheet(
            state.field_spreadsheet,
            state.session.context,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            enemy_declared=state.session.manager.get_enemy_declared_commands(),
            battle_name=state.session.name,
            cache=state.field_sheet_cache,
        )
    except Exception:
        _log_system_error("공개 필드 시트 렌더링")
        system_error = True

    reply_parts = ["◊ 전투 시작"]
    if errors:
        reply_parts.append("⚠️ 오류:\n" + "\n".join(errors))
    if system_error:
        reply_parts.append(_SYSTEM_ERROR_MESSAGE)
    reply_text = "\n".join(reply_parts)

    game_post = _make_phase_post_text(
        RoundPhaseType.ENEMY_PRE_ACTION,
        state.session.round_n,
        state.session,
        state.name_dict,
    )
    return AdminCommandResult(reply_text, game_post, attach_field_image=True)


def _cmd_advance_phase(state: "BotState") -> AdminCommandResult:
    if state.session is None or not state.session.started:
        return AdminCommandResult("◊ 진행 중인 전투가 없습니다.")

    new_phase = state.session.advance_phase()

    # 필드 시트 저장 (커맨드 수신 없는 페이즈에서도)
    system_error = False
    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            is_main=True,
            round_n=state.session.round_n,
            phase=new_phase.value,
            characters=build_field_characters(state.session.context, include_hp=False),
            cache=state.sheet_cache,
        )
    except Exception:
        _log_system_error("필드 시트 저장")
        system_error = True

    try:
        render_public_field_sheet(
            state.field_spreadsheet,
            state.session.context,
            round_n=state.session.round_n,
            phase=new_phase.value,
            enemy_declared=state.session.manager.get_enemy_declared_commands(),
            battle_name=state.session.name,
            cache=state.field_sheet_cache,
        )
    except Exception:
        _log_system_error("공개 필드 시트 렌더링")
        system_error = True

    post_action_results = (
        state.session.manager.get_last_post_action_results()
        if new_phase == RoundPhaseType.ENEMY_POST_ACTION
        else None
    )
    if post_action_results is not None:
        # 적의 POST_ACTION 정산으로 발생한 대미지/힐도 "캐릭터" 시트에 반영한다
        # (개별 캐릭터 커맨드/프록시 경로에서만 write-back하던 기존 갭을 메움).
        post_action_entries = [
            entry
            for part_results in post_action_results.values()
            for part_result in part_results
            for entry in part_result.log_entries
        ]
        write_back_changed_hp(
            state.spreadsheet,
            state.session.context,
            post_action_entries,
            cache=state.sheet_cache,
        )

    round_end_log_entries = (
        state.session.manager.get_last_round_end_log_entries()
        if new_phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY
        else None
    )
    if round_end_log_entries:
        # 라운드 종료 시 발동한 DoT/HoT 등도 "캐릭터"/"에너미" 시트에 반영한다.
        write_back_changed_hp(
            state.spreadsheet,
            state.session.context,
            round_end_log_entries,
            cache=state.sheet_cache,
        )

    eliminated_characters = (
        state.session.manager.get_last_eliminated_characters()
        if new_phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY
        else None
    )

    game_post = _make_phase_post_text(
        new_phase,
        state.session.round_n,
        state.session,
        state.name_dict,
        post_action_results,
        round_end_log_entries,
        eliminated_characters,
    )

    error_suffix = f"\n{_SYSTEM_ERROR_MESSAGE}" if system_error else ""
    reply = f"◊ 페이즈 전환: {new_phase.value}{error_suffix}"

    # 커맨드 수신 없는 페이즈는 active_phase_post_id를 None으로 만들어야 함
    # → 호출측에서 game_post_text가 None인지 여부로 판단하므로
    #   POST_ACTION과 STANDBY는 게시물을 올리되 active_phase_post_id를 None으로 처리
    #   (game_post_text가 있더라도 None 처리하는 건 main.py에서)
    # 필드 상태가 str 대신 이미지로만 표시되므로, 모든 페이즈 전환 게시물에
    # 필드 시트 이미지를 첨부한다.
    return AdminCommandResult(reply, game_post, attach_field_image=True)


def _cmd_continue_battle(state: "BotState") -> AdminCommandResult:
    if state.session is None or not state.session.started:
        return AdminCommandResult("◊ 진행 중인 전투가 없습니다.")
    if state.session.current_phase != RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
        return AdminCommandResult(
            "◊ 라운드 종료 단계에서만 [전투 속행]을 입력할 수 있습니다."
        )

    new_phase = state.session.advance_phase()  # → ENEMY_PRE_ACTION

    system_error = False
    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            is_main=True,
            round_n=state.session.round_n,
            phase=new_phase.value,
            characters=build_field_characters(state.session.context, include_hp=False),
            cache=state.sheet_cache,
        )
    except Exception:
        _log_system_error("필드 시트 저장")
        system_error = True

    try:
        render_public_field_sheet(
            state.field_spreadsheet,
            state.session.context,
            round_n=state.session.round_n,
            phase=new_phase.value,
            enemy_declared=state.session.manager.get_enemy_declared_commands(),
            battle_name=state.session.name,
            cache=state.field_sheet_cache,
        )
    except Exception:
        _log_system_error("공개 필드 시트 렌더링")
        system_error = True

    game_post = _make_phase_post_text(
        new_phase, state.session.round_n, state.session, state.name_dict
    )

    error_suffix = f"\n{_SYSTEM_ERROR_MESSAGE}" if system_error else ""
    reply = f"◊ 라운드 {state.session.round_n} 시작{error_suffix}"
    return AdminCommandResult(reply, game_post, attach_field_image=True)


def _cmd_end(state: "BotState") -> str:
    if state.session is None or not state.session.started:
        return "◊ 진행 중인 전투가 없습니다."

    context = state.session.context
    system_error = False

    # 전투 종료 시점 버프 훅([재앙] 등) 처리 후, 변경된 HP를 스프레드시트에 반영한다.
    battle_end_entries = context.on_battle_end()
    if battle_end_entries:
        try:
            write_back_changed_hp(
                state.spreadsheet,
                context,
                battle_end_entries,
                cache=state.sheet_cache,
            )
        except Exception:
            _log_system_error("전투 종료 처리 HP 반영")
            system_error = True

    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            is_main=True,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            characters=build_field_characters(context, include_hp=False),
            ended=True,
            cache=state.sheet_cache,
        )
    except Exception:
        _log_system_error("필드 시트 저장")
        system_error = True

    try:
        render_public_field_sheet(
            state.field_spreadsheet,
            context,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            enemy_declared=state.session.manager.get_enemy_declared_commands(),
            battle_name=state.session.name,
            cache=state.field_sheet_cache,
        )
    except Exception:
        _log_system_error("공개 필드 시트 렌더링")
        system_error = True

    state.session = None
    state.preparation_status_id = None
    state.active_phase_post_id = None
    state.pending_participants.clear()
    state.pending_placements.clear()

    body_blocks = [
        block
        for block in (
            format_final_hp_roster(context),
            format_battle_end_log_entries(context, battle_end_entries),
        )
        if block
    ]
    result = "◊ 전투 종료"
    if body_blocks:
        result += "\n\n" + "\n\n".join(body_blocks)
    if system_error:
        result += f"\n{_SYSTEM_ERROR_MESSAGE}"
    return result


def _cmd_practice_prep(
    expected_accts: list[str], state: "BotState", visibility: str = "public"
) -> AdminCommandResult:
    if state.practice is not None:
        return AdminCommandResult("◊ 이미 진행 중인 대련/상시전투가 있습니다.")

    (
        buff_dict,
        skill_dict,
        _passive_skill_dict,
        item_dict,
        _inventory,
        state.char_dict,
        state.name_dict,
        state.noncombat_char_dict,
    ) = load_battle_data(state.spreadsheet, cache=state.sheet_cache)
    context = PracticeBattlefieldContext(buff_dict, skill_dict, item_dict)
    manager = PracticeRoundManager(context)
    state.practice = PracticeBattleState(
        context=context,
        manager=manager,
        expected_accts=list(expected_accts),
        visibility=visibility,
    )

    participant_text = (
        " ".join(f"@{a}" for a in expected_accts) if expected_accts else "(없음)"
    )
    game_post = (
        f"◊ 대련 준비\n참여 대상: {participant_text}\n\n"
        "이 게시물에 답글로 포지션을 선언해 주세요.\n"
        "예: [1팀/3열] 또는 [2팀/5열]"
    )
    return AdminCommandResult("", game_post, set_practice_prep_from_game_post=True)


def _cmd_proxy(
    char_name: str, cmd_str: str, state: "BotState"
) -> tuple[str, Optional[BattleCommandLog]]:
    # 상시전투 중 프록시 (적군 커맨드 대행)
    ps = state.practice
    if ps is not None and ps.active_post_id is not None:
        char_id = ps.context.resolve_character_id(CharacterId(char_name))
        if char_id not in ps.context.characters:
            return (
                f"◊ 지정한 캐릭터({char_name})는 대련/상시전투에 참여하고 있지 않습니다.",
                None,
            )

        field_id = str(ps.prep_post_id)
        round_n = ps.round_n
        phase = ps.phase.value if ps.phase is not None else ""

        try:
            command = parse_character_command(char_id, cmd_str, ps.context)
            if command is None:
                return "◊ 커맨드 형식을 인식할 수 없습니다.", None
            result = ps.manager.process_command(command)
            entries = [
                entry
                for part_result in result.part_results
                for entry in part_result.log_entries
            ]
            battle_log = BattleCommandLog(
                field_id=field_id,
                round_n=round_n,
                phase=phase,
                command_text=cmd_str,
                is_main=False,
                entries=entries,
            )
            reply_text = format_battle_reply(ps.context, char_id, result.part_results)
            return reply_text, battle_log
        except CommandValidationError as e:
            battle_log = BattleCommandLog(
                field_id=field_id,
                round_n=round_n,
                phase=phase,
                command_text=cmd_str,
                is_main=False,
                error_trace=traceback.format_exc(),
            )
            return f"◊ {e}", battle_log

    if state.session is None or not state.session.started:
        return "◊ 진행 중인 전투가 없습니다.", None

    char_id = state.session.context.resolve_character_id(CharacterId(char_name))
    if char_id not in state.session.context.characters:
        return f"◊ 지정한 캐릭터({char_name})는 전투에 참여하고 있지 않습니다.", None

    field_id = str(state.preparation_status_id)
    round_n = state.session.round_n
    phase = state.session.current_phase
    is_enemy_declare = (
        state.session.context.characters[char_id].faction == FactionType.ENEMY
    )

    try:
        command = parse_character_command(char_id, cmd_str, state.session.context)
        if command is None:
            return "◊ 커맨드 형식을 인식할 수 없습니다.", None

        before = len(state.session.context.results)
        state.session.context.inventory.cache = state.sheet_cache
        state.session.process_command(command)
        new_results = state.session.context.results[before:]
        entries = [entry for result in new_results for entry in result.log_entries]
        write_back_changed_hp(
            state.spreadsheet, state.session.context, entries, cache=state.sheet_cache
        )

        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            command_text=cmd_str,
            entries=entries,
        )
        reply_text = _format_named_reply(
            state.session.context,
            char_id,
            new_results,
            state.name_dict,
            show_skill_preview=is_enemy_declare,
        )
        if is_enemy_declare:
            reveal_declared_enemy_skills(
                state.spreadsheet,
                state.session.context,
                command,
                cache=state.sheet_cache,
            )
        return reply_text, battle_log
    except CommandValidationError as e:
        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            command_text=cmd_str,
            error_trace=traceback.format_exc(),
        )
        return f"◊ {e}", battle_log


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------


def _assign_random_positions(
    session: "BattleSession",
    ally_data_list: list,
    faction: FactionType,
) -> list[str]:
    """라운드 로빈 + 무작위 방식으로 아군을 열에 배치한다.

    배치에 실패한 캐릭터(체력 0으로 배치 거부된 경우 등)는 조용히
    건너뛰지 않고 오류 메시지로 반환한다 — 호출측이 이를 답글에 포함시켜
    관리자가 문제를 바로 알 수 있게 하고, 원인을 고쳐 [배치/...]로
    재시도할 수 있게 한다."""
    if not ally_data_list:
        return []

    ctx = session.context
    remaining = list(ally_data_list)
    random.shuffle(remaining)

    counts = {col: len(ctx.position_map[faction][col]) for col in _VALID_COLUMNS}
    errors: list[str] = []

    while remaining:
        min_count = min(counts.values())
        eligible = [
            col
            for col in _VALID_COLUMNS
            if counts[col] == min_count and counts[col] < CHARACTER_PER_COLUMN
        ]
        if not eligible:
            break
        random.shuffle(eligible)
        for col in eligible:
            if not remaining:
                break
            data = remaining.pop()
            try:
                session.add_character(data, faction, col)
                counts[col] += 1
            except CommandValidationError as e:
                errors.append(f"{data.name}: {e}")

    return errors


def _make_phase_post_text(
    phase: RoundPhaseType,
    round_n: int,
    session: "BattleSession",
    name_dict: dict[str, "CombatCharacterDataFromSpreadsheet"],
    post_action_results: Optional[
        dict[CharacterId, list[CommandPartProcessResult]]
    ] = None,
    round_end_log_entries: Optional[list[BattleLogEntry]] = None,
    eliminated_characters: Optional[list[CharacterId]] = None,
) -> str:
    # 필드 현황은 게시물에 첨부되는 공개 필드 시트 이미지로 표시하므로, 이
    # 텍스트에는 str(session.context) 보드를 중복으로 넣지 않는다.
    if phase == RoundPhaseType.ENEMY_PRE_ACTION:
        return f"◊ [라운드 {round_n}] 적군 행동 선언"

    if phase == RoundPhaseType.ALLY_ACTION:
        return (
            f"◊ [라운드 {round_n}] 아군 행동\n\n"
            "이 게시물에 답글로 커맨드를 입력해 주세요."
        )

    if phase == RoundPhaseType.ENEMY_POST_ACTION:
        body = _format_enemy_post_action_results(
            session.context, post_action_results or {}, name_dict
        )
        return f"◊ [라운드 {round_n}] 적군 행동 정산 완료\n\n{body}"

    if phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
        header = f"◊ [라운드 {round_n} 종료]"
        tail = "버프/디버프 갱신 완료. [전투 속행] 또는 [전투 종료]를 입력하세요."
        body_blocks = [
            block
            for block in (
                format_round_end_log_entries(
                    session.context, round_end_log_entries or []
                ),
                format_eliminated_characters(eliminated_characters or []),
            )
            if block
        ]
        if body_blocks:
            return f"{header}\n\n{'\n\n'.join(body_blocks)}\n\n{tail}"
        return f"{header}\n\n{tail}"

    return ""


def _damaged_target_mentions(
    part_result: CommandPartProcessResult,
    name_dict: dict[str, "CombatCharacterDataFromSpreadsheet"],
) -> str:
    """part_result의 대미지 로그가 가리키는 대상들 중, "캐릭터" 시트에 등록된
    (mastodon 계정이 있는) 대상들을 멘션 문자열로 만든다. 소환수 등 계정이
    없는 대상은 name_dict에 없으므로 자연히 제외된다."""
    target_names = dict.fromkeys(
        entry.target_name
        for entry in part_result.log_entries
        if entry.kind == BattleLogEntryKind.DAMAGE
    )
    accts = [
        data.mastodon_id
        for name in target_names
        if (data := name_dict.get(name)) is not None and data.mastodon_id
    ]
    return " ".join(f"@{acct}" for acct in accts)


def _format_named_reply(
    context: "BattlefieldContext",
    char_id: CharacterId,
    part_results: list[CommandPartProcessResult],
    name_dict: dict[str, "CombatCharacterDataFromSpreadsheet"],
    *,
    show_skill_preview: bool = False,
) -> str:
    """part_results를 커맨드(파트) 하나당 "{이름} 【헤더】/계산식" 블록으로
    조립한다. 여러 파트가 있으면 각각 별도 블록으로 빈 줄(\\n\\n)로 구분한다.

    프록시(관리자 대행) 답글은 실제로 행동한 캐릭터가 누구인지 답글 자체만
    보고는 알 수 없으므로(직접 답글과 달리 caster에게 보내는 답글이 아님),
    헤더 앞에 이름을 붙인다. 공격/스킬로 대미지를 입은 대상이 있으면 그
    계정을 헤더 줄에 멘션해 당사자에게 알린다.
    """
    blocks = []
    for part_result in part_results:
        block = format_battle_reply(
            context, char_id, [part_result], show_skill_preview=show_skill_preview
        )
        if not block:
            continue
        mentions = _damaged_target_mentions(part_result, name_dict)
        header_line, sep, rest = block.partition("\n")
        if mentions:
            header_line = f"{header_line} {mentions}"
        block = header_line + sep + rest
        blocks.append(f"{char_id.name} {block}")
    return "\n\n".join(blocks)


def _format_enemy_post_action_results(
    context: "BattlefieldContext",
    post_action_results: dict[CharacterId, list[CommandPartProcessResult]],
    name_dict: dict[str, "CombatCharacterDataFromSpreadsheet"],
) -> str:
    """ENEMY_POST_ACTION 정산 결과를 "{적 이름} 【헤더】/계산식" 블록으로
    조립한다. 커맨드(파트) 하나당 블록 하나이며, 같은 적의 커맨드가
    여러 개여도 각각 별도 블록으로 빈 줄(\\n\\n)로 구분한다.

    이동은 PRE 선언 시점에 이미 답글로 안내되었으므로 여기서는 제외한다
    (POST 재전개 시 move_list가 빈 채로 남아 헤더만 중복 출력되는 것을 막는다).
    """
    blocks = []
    for user_id, part_results in post_action_results.items():
        non_move_results = [
            r
            for r in part_results
            if r.expanded_part.original_part is None
            or r.expanded_part.original_part.type_ != ActionType.MOVE
        ]
        block = _format_named_reply(context, user_id, non_move_results, name_dict)
        if block:
            blocks.append(block)
    return "\n\n".join(blocks) if blocks else "변동 없음"


# ---------------------------------------------------------------------------
# 상시전투 핸들러
# ---------------------------------------------------------------------------


def _cmd_investigation_battle(
    text: str, mentions: list[str], state: "BotState", visibility: str = "public"
) -> AdminCommandResult:
    """[상시전투] 커맨드: 적군을 즉시 배치하고 아군 포지션 선언 대기 안내를 게시한다."""
    if state.practice is not None:
        return AdminCommandResult("◊ 이미 진행 중인 대련/상시전투가 있습니다.")

    (
        buff_dict,
        skill_dict,
        _passive_skill_dict,
        item_dict,
        _inventory,
        state.char_dict,
        state.name_dict,
        state.noncombat_char_dict,
    ) = load_battle_data(state.spreadsheet, cache=state.sheet_cache)
    context = PracticeBattlefieldContext(buff_dict, skill_dict, item_dict)
    manager = PracticeRoundManager(context)
    state.practice = PracticeBattleState(
        context=context,
        manager=manager,
        is_investigation=True,
        expected_accts=list(mentions),
        visibility=visibility,
    )

    errors: list[str] = []

    # 같은 메시지에 포함된 [배치/이름/진영 열]을 파싱해 즉시 등록
    for m in _RE_MANUAL_PLACE.finditer(text):
        name = m.group(1).strip()
        faction_col_str = m.group(2).strip()
        parts = faction_col_str.split()
        if len(parts) < 2:
            errors.append(
                "◊ 캐릭터 배치는 [배치/(캐릭터 이름)/(진영) 0열] 형식을 따라야 합니다. (예시: [배치/늑대/적군 3열])"
            )
            continue
        faction_str, col_str = parts[0], parts[1]
        name = resolve_matching_key(name, state.name_dict.keys())
        data = state.name_dict.get(name)
        if data is None:
            errors.append(f"캐릭터({name})를 찾을 수 없습니다.")
            continue
        try:
            faction = FactionType(faction_str)
            side = SideType.SIDE_1 if faction == FactionType.ALLY else SideType.SIDE_2
            column = BattlefieldColumnIndex.from_str(col_str)
            context.add_character(data, side, column)
        except (ValueError, CommandValidationError) as e:
            errors.append(str(e))

    participant_text = " ".join(f"@{a}" for a in mentions) if mentions else "(없음)"
    game_post = (
        f"◊ 상시전투 준비\n참여 대상: {participant_text}\n\n"
        "이 게시물에 답글로 포지션을 선언해 주세요.\n"
        "예: [아군/3열]"
    )
    if errors:
        game_post += "\n\n⚠️ 오류:\n" + "\n".join(errors)

    return AdminCommandResult("", game_post, set_practice_prep_from_game_post=True)


# ---------------------------------------------------------------------------
# DM 전투 핸들러
# ---------------------------------------------------------------------------


def _dm_battle_column_token(raw: str) -> str:
    """DM 전투의 [배치/이름/열] 문법은 진영 지정이 없다(배치 대상이 항상
    적군으로 고정이라 무의미하기 때문) — 본 전투 문법인 [배치/이름/적군 N열]을
    실수로 그대로 써도(예: "적군 4열") 에러 없이 마지막 토큰(열 표기)만
    조용히 취한다."""
    parts = raw.split()
    return parts[-1] if parts else raw


def _cmd_dm_battle_start(
    text: str, mentions: list[str], state: "BotState", visibility: str
) -> AdminCommandResult:
    """[전투 발생] 커맨드: 본 전투와 동일한 풀스탯 BattleSession을 만들어
    적을 [배치/이름/열]로 즉시 배치하고, 이 DM에 함께 멘션되어 "캐릭터"
    시트에 등록된 계정을 겹침 없이 무작위로 아군 배치한 뒤 바로 전투를
    시작한다 — 본 전투와 달리 참전 신청/[전투준비]/[전투개시] 단계가 없다."""
    (
        buff_dict,
        skill_dict,
        passive_skill_dict,
        item_dict,
        inventory,
        state.char_dict,
        state.name_dict,
        state.noncombat_char_dict,
    ) = load_battle_data(state.spreadsheet, cache=state.sheet_cache)
    session = BattleSession(
        buff_dict, skill_dict, passive_skill_dict, item_dict, inventory
    )

    errors: list[str] = []
    for m in _RE_MANUAL_PLACE.finditer(text):
        name = resolve_matching_key(m.group(1).strip(), state.name_dict.keys())
        data = state.name_dict.get(name)
        if data is None:
            errors.append(f"지정된 캐릭터({name})를 찾을 수 없습니다.")
            continue
        try:
            column = BattlefieldColumnIndex.from_str(
                _dm_battle_column_token(m.group(2).strip())
            )
            session.add_character(data, FactionType.ENEMY, column)
        except (ValueError, CommandValidationError) as e:
            errors.append(str(e))

    participant_accts = [acct for acct in mentions if acct in state.char_dict]
    ally_data_list = [state.char_dict[acct] for acct in participant_accts]
    errors.extend(_assign_random_positions(session, ally_data_list, FactionType.ALLY))

    if not session.context.characters:
        reply_parts = ["◊ 배치에 모두 실패하여 전투를 시작하지 못했습니다."]
        if errors:
            reply_parts.append("⚠️ 오류:\n" + "\n".join(errors))
        return AdminCommandResult("\n".join(reply_parts))

    session.start()
    dm_state = DmBattleState(
        session=session,
        field_id="",
        active_post_id=0,
        visibility=visibility,
        mentions=participant_accts,
    )

    game_post = _dm_mention_prefix(dm_state) + _make_phase_post_text(
        RoundPhaseType.ENEMY_PRE_ACTION, session.round_n, session, state.name_dict
    )
    game_post += f"\n\n{session.context}"
    if errors:
        game_post += "\n\n⚠️ 오류:\n" + "\n".join(errors)

    return AdminCommandResult("", game_post, dm_battle_to_register=dm_state)


def _cmd_dm_battle_advance_phase(
    dm_state: DmBattleState, state: "BotState"
) -> AdminCommandResult:
    session = dm_state.session
    new_phase = session.advance_phase()

    post_action_results = (
        session.manager.get_last_post_action_results()
        if new_phase == RoundPhaseType.ENEMY_POST_ACTION
        else None
    )
    if post_action_results is not None:
        post_action_entries = [
            entry
            for part_results in post_action_results.values()
            for part_result in part_results
            for entry in part_result.log_entries
        ]
        write_back_changed_hp(
            state.spreadsheet,
            session.context,
            post_action_entries,
            cache=state.sheet_cache,
        )

    round_end_log_entries = (
        session.manager.get_last_round_end_log_entries()
        if new_phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY
        else None
    )
    if round_end_log_entries:
        write_back_changed_hp(
            state.spreadsheet,
            session.context,
            round_end_log_entries,
            cache=state.sheet_cache,
        )

    eliminated_characters = (
        session.manager.get_last_eliminated_characters()
        if new_phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY
        else None
    )

    winner = _check_dm_battle_wipe(dm_state)
    if winner is not None:
        end_text = _end_dm_battle(dm_state, state, winner)
        return AdminCommandResult(
            "◊ 페이즈 전환 처리 완료",
            end_text,
            game_post_reply_to_confirmation=True,
            game_post_visibility=dm_state.visibility,
        )

    game_post = _dm_mention_prefix(dm_state) + _make_phase_post_text(
        new_phase,
        session.round_n,
        session,
        state.name_dict,
        post_action_results,
        round_end_log_entries,
        eliminated_characters,
    )
    game_post += f"\n\n{session.context}"

    return AdminCommandResult(
        f"◊ 페이즈 전환: {new_phase.value}",
        game_post,
        dm_battle_to_register=dm_state,
        game_post_reply_to_confirmation=True,
        game_post_visibility=dm_state.visibility,
    )


def _cmd_dm_battle_continue(
    dm_state: DmBattleState, state: "BotState"
) -> AdminCommandResult:
    session = dm_state.session
    if session.current_phase != RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
        return AdminCommandResult(
            "◊ 라운드 종료 단계에서만 [전투 속행]을 입력할 수 있습니다."
        )

    new_phase = session.advance_phase()  # → ENEMY_PRE_ACTION
    game_post = _dm_mention_prefix(dm_state) + _make_phase_post_text(
        new_phase, session.round_n, session, state.name_dict
    )
    game_post += f"\n\n{session.context}"

    return AdminCommandResult(
        f"◊ 라운드 {session.round_n} 시작",
        game_post,
        dm_battle_to_register=dm_state,
        game_post_reply_to_confirmation=True,
        game_post_visibility=dm_state.visibility,
    )


def _cmd_dm_battle_end(dm_state: DmBattleState, state: "BotState") -> str:
    """관리자가 [전투종료]로 강제 종료한다 — 전멸 시 자동 종료의 안전장치."""
    return _end_dm_battle(dm_state, state, winner=None)


def _cmd_dm_battle_proxy(
    dm_state: DmBattleState, char_name: str, cmd_str: str, state: "BotState"
) -> tuple[str, Optional[BattleCommandLog]]:
    session = dm_state.session
    char_id = session.context.resolve_character_id(CharacterId(char_name))
    if char_id not in session.context.characters:
        return f"◊ 지정한 캐릭터({char_name})는 전투에 참여하고 있지 않습니다.", None

    field_id = dm_state.field_id
    round_n = session.round_n
    phase = session.current_phase
    is_enemy_declare = session.context.characters[char_id].faction == FactionType.ENEMY

    try:
        command = parse_character_command(char_id, cmd_str, session.context)
        if command is None:
            return "◊ 커맨드 형식을 인식할 수 없습니다.", None

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
            command_text=cmd_str,
            entries=entries,
        )
        reply_text = _format_named_reply(
            session.context,
            char_id,
            new_results,
            state.name_dict,
            show_skill_preview=is_enemy_declare,
        )
        if is_enemy_declare:
            reveal_declared_enemy_skills(
                state.spreadsheet, session.context, command, cache=state.sheet_cache
            )
        return f"{reply_text}\n\n{session.context}", battle_log
    except CommandValidationError as e:
        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            command_text=cmd_str,
            error_trace=traceback.format_exc(),
        )
        return f"◊ {e}\n\n{session.context}", battle_log


def _check_dm_battle_wipe(dm_state: DmBattleState) -> Optional[FactionType]:
    """진영별 HP 합산 후 한쪽이 전멸했으면 승리 진영을 반환한다."""
    hp_by_faction: dict[FactionType, int] = {
        FactionType.ALLY: 0,
        FactionType.ENEMY: 0,
    }
    for char in dm_state.session.context.characters.values():
        hp_by_faction[char.faction] += char.status.curr_hp

    ally_wiped = hp_by_faction[FactionType.ALLY] <= 0
    enemy_wiped = hp_by_faction[FactionType.ENEMY] <= 0
    if ally_wiped == enemy_wiped:
        return None
    return FactionType.ALLY if enemy_wiped else FactionType.ENEMY


def _end_dm_battle(
    dm_state: DmBattleState, state: "BotState", winner: Optional[FactionType]
) -> str:
    """DM 전투를 종료 처리한다(전멸 자동 종료/관리자 수동 종료 공용).

    본 전투의 _cmd_end와 동일하게 전투 종료 시점 버프 훅([재앙] 등) 처리 후
    변경된 HP를 "캐릭터" 시트에 반영하고, state.dm_battles에서 이 세션을
    제거한다."""
    session = dm_state.session
    battle_end_entries = session.context.on_battle_end()
    if battle_end_entries:
        write_back_changed_hp(
            state.spreadsheet,
            session.context,
            battle_end_entries,
            cache=state.sheet_cache,
        )

    state.dm_battles.pop(dm_state.active_post_id, None)

    result = f"◊ 전투 종료 (라운드 {session.round_n})"
    if winner is not None:
        result += f"\n\n승자: {winner.value}"

    body_blocks = [
        block
        for block in (
            format_final_hp_roster(session.context),
            format_battle_end_log_entries(session.context, battle_end_entries),
        )
        if block
    ]
    if body_blocks:
        result += "\n\n" + "\n\n".join(body_blocks)
    return f"{_dm_mention_prefix(dm_state)}{result}"


def find_dm_battle_by_field_id(
    state: "BotState", field_id: str
) -> Optional[DmBattleState]:
    """field_id(전투 개시 게시물 id)로 진행 중인 DmBattleState를 찾는다.

    state.dm_battles는 스레드 tip post_id(페이즈 전환마다 바뀜)를 키로 쓰므로,
    안정적인 field_id로 찾으려면 값들을 선형 탐색해야 한다 — 동시 진행되는 DM
    전투 수가 적어(수 개 이내) 성능에 문제되지 않는다."""
    return next(
        (dm for dm in state.dm_battles.values() if dm.field_id == field_id), None
    )
