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

from bot.battle_reply_text import format_battle_reply
from bot.field_sheet_renderer import render_public_field_sheet
from bot.load_data import load_battle_data
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
_RE_PROXY = re.compile(r"^([^\[\]]+?)\s+(\[.+])$", re.DOTALL)

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


def handle_admin_command(
    text: str, state: "BotState", mentions: list[str] | None = None
) -> AdminCommandResult:
    """
    어드민 커맨드 텍스트를 파싱해 처리하고 AdminCommandResult를 반환한다.
    game_post_text가 None이 아니면 호출측에서 퍼블릭 게시물로 게시한다.
    """
    if _RE_BATTLE_PREP.search(text):
        return _cmd_battle_prep(state)

    if _RE_MANUAL_PLACE.search(text):
        m = _RE_MANUAL_PLACE.search(text)
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

    if _RE_INVESTIGATION_BATTLE.search(text):
        return _cmd_investigation_battle(text, mentions or [], state)

    if _RE_PRACTICE_PREP.search(text):
        return _cmd_practice_prep(mentions or [], state)

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
    ) = load_battle_data(state.spreadsheet)
    state.session = BattleSession(
        buff_dict,
        skill_dict,
        passive_skill_dict,
        item_dict,
        inventory,
    )
    reply = "◊ 전투 준비\n\n참여를 희망하는 인원은 이곳에 답글을 남겨주세요."
    return AdminCommandResult(
        reply, set_preparation_post=True, post_as_new_status=True
    )


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
    _assign_random_positions(state.session, ally_data_list, FactionType.ALLY)

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
    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            is_main=True,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            characters=build_field_characters(
                state.session.context, include_hp=False
            ),
        )
    except Exception as e:
        errors.append(f"스프레드시트 저장 실패: {e}")

    try:
        render_public_field_sheet(
            state.field_spreadsheet,
            state.session.context,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            enemy_declared=state.session.manager.get_enemy_declared_commands(),
            battle_name=state.session.name,
        )
    except Exception as e:
        errors.append(f"공개 필드 시트 렌더링 실패: {e}")

    reply_parts = ["◊ 전투 시작"]
    if errors:
        reply_parts.append("⚠️ 오류:\n" + "\n".join(errors))
    reply_text = "\n".join(reply_parts)

    game_post = _make_phase_post_text(
        RoundPhaseType.ENEMY_PRE_ACTION,
        state.session.round_n,
        state.session,
    )
    return AdminCommandResult(reply_text, game_post, attach_field_image=True)


def _cmd_advance_phase(state: "BotState") -> AdminCommandResult:
    if state.session is None or not state.session.started:
        return AdminCommandResult("◊ 진행 중인 전투가 없습니다.")

    new_phase = state.session.advance_phase()

    # 필드 시트 저장 (커맨드 수신 없는 페이즈에서도)
    errors: list[str] = []
    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            is_main=True,
            round_n=state.session.round_n,
            phase=new_phase.value,
            characters=build_field_characters(
                state.session.context, include_hp=False
            ),
        )
    except Exception as e:
        errors.append(f"스프레드시트 저장 실패: {e}")

    try:
        render_public_field_sheet(
            state.field_spreadsheet,
            state.session.context,
            round_n=state.session.round_n,
            phase=new_phase.value,
            enemy_declared=state.session.manager.get_enemy_declared_commands(),
            battle_name=state.session.name,
        )
    except Exception as e:
        errors.append(f"공개 필드 시트 렌더링 실패: {e}")

    post_action_results = (
        state.session.manager.get_last_post_action_results()
        if new_phase == RoundPhaseType.ENEMY_POST_ACTION
        else None
    )
    game_post = _make_phase_post_text(
        new_phase, state.session.round_n, state.session, post_action_results
    )

    error_suffix = ("\n⚠️ " + "; ".join(errors)) if errors else ""
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

    errors: list[str] = []
    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            is_main=True,
            round_n=state.session.round_n,
            phase=new_phase.value,
            characters=build_field_characters(
                state.session.context, include_hp=False
            ),
        )
    except Exception as e:
        errors.append(f"스프레드시트 저장 실패: {e}")

    try:
        render_public_field_sheet(
            state.field_spreadsheet,
            state.session.context,
            round_n=state.session.round_n,
            phase=new_phase.value,
            enemy_declared=state.session.manager.get_enemy_declared_commands(),
            battle_name=state.session.name,
        )
    except Exception as e:
        errors.append(f"공개 필드 시트 렌더링 실패: {e}")

    game_post = _make_phase_post_text(new_phase, state.session.round_n, state.session)

    error_suffix = ("\n⚠️ " + "; ".join(errors)) if errors else ""
    reply = f"◊ 라운드 {state.session.round_n} 시작{error_suffix}"
    return AdminCommandResult(reply, game_post, attach_field_image=True)


def _cmd_end(state: "BotState") -> str:
    if state.session is None or not state.session.started:
        return "◊ 진행 중인 전투가 없습니다."

    errors: list[str] = []

    # 전투 종료 시점 버프 훅([재앙] 등) 처리 후, 변경된 HP를 스프레드시트에 반영한다.
    hp_before = {
        char_id: char.status.curr_hp
        for char_id, char in state.session.context.characters.items()
    }
    state.session.context.on_battle_end()
    battle_end_entries = [
        BattleLogEntry(
            target_name=char_id.name,
            kind=BattleLogEntryKind.DAMAGE,
            result=f"대미지 {before - char.status.curr_hp}",
            value=before - char.status.curr_hp,
        )
        for char_id, char in state.session.context.characters.items()
        if (before := hp_before[char_id]) != char.status.curr_hp
    ]
    if battle_end_entries:
        try:
            write_back_changed_hp(
                state.spreadsheet, state.session.context, battle_end_entries
            )
        except Exception as e:
            errors.append(f"전투 종료 처리 HP 반영 실패: {e}")

    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            is_main=True,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            characters=build_field_characters(
                state.session.context, include_hp=False
            ),
            ended=True,
        )
    except Exception as e:
        errors.append(f"스프레드시트 저장 실패: {e}")

    try:
        render_public_field_sheet(
            state.field_spreadsheet,
            state.session.context,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            enemy_declared=state.session.manager.get_enemy_declared_commands(),
            battle_name=state.session.name,
        )
    except Exception as e:
        errors.append(f"공개 필드 시트 렌더링 실패: {e}")

    state.session = None
    state.preparation_status_id = None
    state.active_phase_post_id = None
    state.pending_participants.clear()
    state.pending_placements.clear()

    result = "◊ 전투 종료"
    if errors:
        result += "\n⚠️ " + "; ".join(errors)
    return result


def _cmd_practice_prep(
    expected_accts: list[str], state: "BotState"
) -> AdminCommandResult:
    if state.practice is not None:
        return AdminCommandResult("◊ 이미 진행 중인 대련/상시전투가 있습니다.")

    (
        buff_dict,
        skill_dict,
        _passive_skill_dict,
        _item_dict,
        _inventory,
        state.char_dict,
        state.name_dict,
        state.noncombat_char_dict,
    ) = load_battle_data(state.spreadsheet)
    context = PracticeBattlefieldContext(buff_dict, skill_dict)
    manager = PracticeRoundManager(context)
    state.practice = PracticeBattleState(
        context=context,
        manager=manager,
        expected_accts=list(expected_accts),
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

    try:
        command = parse_character_command(char_id, cmd_str, state.session.context)
        if command is None:
            return "◊ 커맨드 형식을 인식할 수 없습니다.", None

        before = len(state.session.context.results)
        state.session.process_command(command)
        new_results = state.session.context.results[before:]
        entries = [entry for result in new_results for entry in result.log_entries]
        write_back_changed_hp(state.spreadsheet, state.session.context, entries)

        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            command_text=cmd_str,
            entries=entries,
        )
        reply_text = format_battle_reply(state.session.context, char_id, new_results)
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
) -> None:
    """라운드 로빈 + 무작위 방식으로 아군을 열에 배치한다."""
    if not ally_data_list:
        return

    ctx = session.context
    remaining = list(ally_data_list)
    random.shuffle(remaining)

    counts = {col: len(ctx.position_map[faction][col]) for col in _VALID_COLUMNS}

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
            except CommandValidationError:
                pass


def _make_phase_post_text(
    phase: RoundPhaseType,
    round_n: int,
    session: "BattleSession",
    post_action_results: Optional[
        dict[CharacterId, list[CommandPartProcessResult]]
    ] = None,
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
            session.context, post_action_results or {}
        )
        return f"◊ [라운드 {round_n}] 적군 행동 정산 완료\n\n{body}"

    if phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
        return (
            f"◊ [라운드 {round_n} 종료]\n\n"
            f"버프/디버프 갱신 완료. [전투 속행] 또는 [전투 종료]를 입력하세요."
        )

    return ""


def _format_enemy_post_action_results(
    context: "BattlefieldContext",
    post_action_results: dict[CharacterId, list[CommandPartProcessResult]],
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
        for part_result in non_move_results:
            block = format_battle_reply(context, user_id, [part_result])
            if block:
                blocks.append(f"{user_id.name} {block}")
    return "\n\n".join(blocks) if blocks else "변동 없음"


# ---------------------------------------------------------------------------
# 상시전투 핸들러
# ---------------------------------------------------------------------------


def _cmd_investigation_battle(
    text: str, mentions: list[str], state: "BotState"
) -> AdminCommandResult:
    """[상시전투] 커맨드: 적군을 즉시 배치하고 아군 포지션 선언 대기 안내를 게시한다."""
    if state.practice is not None:
        return AdminCommandResult("◊ 이미 진행 중인 대련/상시전투가 있습니다.")

    (
        buff_dict,
        skill_dict,
        _passive_skill_dict,
        _item_dict,
        _inventory,
        state.char_dict,
        state.name_dict,
        state.noncombat_char_dict,
    ) = load_battle_data(state.spreadsheet)
    context = PracticeBattlefieldContext(buff_dict, skill_dict)
    manager = PracticeRoundManager(context)
    state.practice = PracticeBattleState(
        context=context,
        manager=manager,
        is_investigation=True,
        expected_accts=list(mentions),
    )

    errors: list[str] = []

    # 같은 메시지에 포함된 [배치/이름/진영 열]을 파싱해 즉시 등록
    for m in _RE_MANUAL_PLACE.finditer(text):
        name = m.group(1).strip()
        faction_col_str = m.group(2).strip()
        parts = faction_col_str.split()
        if len(parts) < 2:
            errors.append(
                f"◊ 캐릭터 배치는 [배치/(캐릭터 이름)/(진영) 0열] 형식을 따라야 합니다. (예시: [배치/늑대/적군 3열])"
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


def _assign_random_positions_practice(
    context: PracticeBattlefieldContext,
    data_list: list,
    side: SideType,
) -> None:
    """연습 전투용 무작위 배치 헬퍼."""
    from battle.objects.define import FactionType

    faction = FactionType.ALLY if side == SideType.SIDE_1 else FactionType.ENEMY
    remaining = list(data_list)
    random.shuffle(remaining)
    counts = {col: len(context.position_map[faction][col]) for col in _VALID_COLUMNS}

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
                context.add_character(data, side, col)
                counts[col] += 1
            except CommandValidationError:
                pass
