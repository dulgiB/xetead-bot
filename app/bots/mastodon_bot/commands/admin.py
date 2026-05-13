import random
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.exceptions import CommandValidationError
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    BattlefieldColumnIndex,
    FactionType,
)
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from bots.mastodon_bot.main import BotState
    from bots.mastodon_bot.session import BattleSession

_RE_BATTLE_PREP = re.compile(r"\[전투\s*준비]")
_RE_MANUAL_PLACE = re.compile(r"\[배치\s*/\s*([^/\]]+?)\s*/\s*([^/\]]+)]")
_RE_BATTLE_START = re.compile(r"\[전투\s*시작]")
_RE_PHASE = re.compile(r"\[페이즈]")
_RE_CONTINUE = re.compile(r"\[전투\s*속행]")
_RE_STATUS = re.compile(r"\[현황]")
_RE_END = re.compile(r"\[전투\s*종료]")
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


def handle_admin_command(text: str, state: "BotState") -> AdminCommandResult:
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
        return _cmd_battle_start(state)

    if _RE_PHASE.search(text):
        return _cmd_advance_phase(state)

    if _RE_CONTINUE.search(text):
        return _cmd_continue_battle(state)

    if _RE_STATUS.search(text):
        return AdminCommandResult(_cmd_status(state))

    if _RE_END.search(text):
        return AdminCommandResult(_cmd_end(state))

    if m := _RE_PROXY.match(text):
        char_name = m.group(1).strip()
        cmd_str = m.group(2).strip()
        return AdminCommandResult(_cmd_proxy(char_name, cmd_str, state))

    return AdminCommandResult("알 수 없는 관리자 커맨드입니다.")


# ---------------------------------------------------------------------------
# 개별 커맨드 핸들러
# ---------------------------------------------------------------------------


def _cmd_battle_prep(state: "BotState") -> AdminCommandResult:
    from bots.mastodon_bot.session import BattleSession

    if state.session is not None:
        return AdminCommandResult("이미 진행 중인 세션이 있습니다.")

    state.session = BattleSession(state.buff_dict, state.skill_dict)
    reply = (
        "전투 준비 세션이 생성되었습니다.\n"
        f"등록된 캐릭터: {len(state.char_dict)}명\n"
        "이 게시물에 답글을 달면 참전 신청으로 처리됩니다.\n"
        "계정 없는 캐릭터는 [배치/이름/팩션 열] 형식으로 admin이 직접 배치하세요."
    )
    return AdminCommandResult(reply, set_preparation_post=True)


def _cmd_manual_place(name: str, faction_col_str: str, state: "BotState") -> str:
    if state.session is None:
        return "진행 중인 세션이 없습니다. 먼저 [전투 준비]를 입력하세요."
    if state.session.started:
        return "전투가 이미 시작되었습니다."
    if name not in state.name_dict:
        return f"캐릭터 '{name}'을(를) 찾을 수 없습니다."

    parts = faction_col_str.split()
    if len(parts) < 2:
        return "형식 오류: [배치/이름/팩션 열] 예시 → [배치/늑대/적군 3열]"

    faction_str = parts[0]
    col_str = parts[1]

    try:
        faction = FactionType(faction_str)
    except ValueError:
        return f"팩션 '{faction_str}'은 '아군' 또는 '적군'이어야 합니다."

    try:
        column = BattlefieldColumnIndex.from_str(col_str)
    except ValueError:
        return f"열 '{col_str}'을 인식할 수 없습니다. 예: 1열, 2, 3열 등"

    state.pending_placements.append((name, faction, column))
    return f"{name}({faction.value} {column}열)을 수동 배치 목록에 추가했습니다."


def _cmd_battle_start(state: "BotState") -> AdminCommandResult:
    import datetime

    if state.session is None:
        return AdminCommandResult(
            "진행 중인 세션이 없습니다. 먼저 [전투 준비]를 입력하세요."
        )
    if state.session.started:
        return AdminCommandResult("전투가 이미 시작되었습니다.")
    if not state.pending_participants and not state.pending_placements:
        return AdminCommandResult(
            "배치된 캐릭터가 없습니다. 참전 신청이나 [배치/...] 커맨드를 먼저 입력하세요."
        )

    # 1. 수동 배치 처리 (pending_placements)
    errors: list[str] = []
    for name, faction, column in state.pending_placements:
        data = state.name_dict.get(name)
        if data is None:
            errors.append(f"캐릭터 '{name}'을 찾을 수 없습니다.")
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

    # 3. 전투 시작
    state.session.start()
    state.battle_key = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 4. 스프레드시트 저장
    from bots.mastodon_bot.battle_persistence import save_battle_state

    try:
        save_battle_state(state.spreadsheet, state)
    except Exception as e:
        errors.append(f"스프레드시트 저장 실패: {e}")

    reply_parts = ["전투가 시작되었습니다!"]
    if errors:
        reply_parts.append("⚠️ 오류:\n" + "\n".join(errors))
    reply_text = "\n".join(reply_parts)

    game_post = _make_phase_post_text(
        RoundPhaseType.ENEMY_PRE_ACTION,
        state.session.round_n,
        state.session,
    )
    return AdminCommandResult(reply_text, game_post)


def _cmd_advance_phase(state: "BotState") -> AdminCommandResult:
    if state.session is None or not state.session.started:
        return AdminCommandResult("진행 중인 전투가 없습니다.")

    # POST_ACTION 직전 HP 스냅샷 (결과 발표에 사용)
    hp_before: Optional[dict] = None
    if state.session.current_phase == RoundPhaseType.ALLY_ACTION:
        hp_before = {
            cid: char.status.curr_hp
            for cid, char in state.session.context.characters.items()
        }

    new_phase = state.session.advance_phase()

    # 스프레드시트 저장 (커맨드 수신 없는 페이즈에서도)
    errors: list[str] = []
    from bots.mastodon_bot.battle_persistence import save_battle_state

    try:
        save_battle_state(state.spreadsheet, state)
    except Exception as e:
        errors.append(f"스프레드시트 저장 실패: {e}")

    game_post = _make_phase_post_text(
        new_phase, state.session.round_n, state.session, hp_before
    )

    error_suffix = ("\n⚠️ " + "; ".join(errors)) if errors else ""
    reply = f"페이즈 전환: {new_phase.value}{error_suffix}"

    # 커맨드 수신 없는 페이즈는 active_phase_post_id를 None으로 만들어야 함
    # → 호출측에서 game_post_text가 None인지 여부로 판단하므로
    #   POST_ACTION과 STANDBY는 게시물을 올리되 active_phase_post_id를 None으로 처리
    #   (game_post_text가 있더라도 None 처리하는 건 main.py에서)
    return AdminCommandResult(reply, game_post)


def _cmd_continue_battle(state: "BotState") -> AdminCommandResult:
    if state.session is None or not state.session.started:
        return AdminCommandResult("진행 중인 전투가 없습니다.")
    if state.session.current_phase != RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
        return AdminCommandResult(
            "라운드 종료 단계에서만 [전투 속행]을 입력할 수 있습니다."
        )

    new_phase = state.session.advance_phase()  # → ENEMY_PRE_ACTION

    errors: list[str] = []
    from bots.mastodon_bot.battle_persistence import save_battle_state

    try:
        save_battle_state(state.spreadsheet, state)
    except Exception as e:
        errors.append(f"스프레드시트 저장 실패: {e}")

    game_post = _make_phase_post_text(new_phase, state.session.round_n, state.session)

    error_suffix = ("\n⚠️ " + "; ".join(errors)) if errors else ""
    reply = f"라운드 {state.session.round_n} 시작{error_suffix}"
    return AdminCommandResult(reply, game_post)


def _cmd_status(state: "BotState") -> str:
    if state.session is None:
        return "진행 중인 세션이 없습니다."
    return str(state.session.context)


def _cmd_end(state: "BotState") -> str:
    if state.session is None or not state.session.started:
        return "진행 중인 전투가 없습니다."

    errors: list[str] = []
    from bots.mastodon_bot.battle_persistence import mark_battle_finished

    try:
        if state.battle_key:
            mark_battle_finished(state.spreadsheet, state.battle_key)
    except Exception as e:
        errors.append(f"스프레드시트 저장 실패: {e}")

    state.session = None
    state.battle_key = None
    state.preparation_status_id = None
    state.active_phase_post_id = None
    state.pending_participants.clear()
    state.pending_placements.clear()

    result = "전투가 종료되었습니다."
    if errors:
        result += "\n⚠️ " + "; ".join(errors)
    return result


def _cmd_proxy(char_name: str, cmd_str: str, state: "BotState") -> str:
    if state.session is None or not state.session.started:
        return "진행 중인 전투가 없습니다."

    char_id = CharacterId(char_name)
    if char_id not in state.session.context.characters:
        return f"캐릭터 '{char_name}'은(는) 현재 전장에 없습니다."

    try:
        command = parse_character_command(char_id, cmd_str)
        if command is None:
            return "커맨드 형식을 인식할 수 없습니다."
        state.session.process_command(command)
        return str(state.session.context)
    except CommandValidationError as e:
        return str(e)


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
    hp_before: Optional[dict] = None,
) -> str:
    if phase == RoundPhaseType.ENEMY_PRE_ACTION:
        return (
            f"⚔️ 라운드 {round_n} — 적군 행동 선언 단계입니다.\n"
            "이 게시물에 답글로 적군 커맨드를 입력하세요.\n"
            f"\n{session.context}"
        )

    if phase == RoundPhaseType.ALLY_ACTION:
        return (
            f"🛡️ 라운드 {round_n} — 아군 행동 단계입니다.\n"
            "이 게시물에 답글로 아군 커맨드를 입력하세요.\n"
            f"\n{session.context}"
        )

    if phase == RoundPhaseType.ENEMY_POST_ACTION:
        result_lines = _format_hp_changes(session, hp_before)
        body = "\n".join(result_lines) if result_lines else "변동 없음"
        return (
            f"🔴 라운드 {round_n} — 적군 행동 정산 완료.\n{body}\n\n{session.context}"
        )

    if phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
        return (
            f"⏳ 라운드 {round_n} 종료. 버프/디버프 갱신 완료.\n"
            "admin이 [전투 속행] 또는 [전투 종료]를 입력하세요.\n"
            f"\n{session.context}"
        )

    return str(session.context)


def _format_hp_changes(
    session: "BattleSession", hp_before: Optional[dict]
) -> list[str]:
    if hp_before is None:
        return []
    lines = []
    for char_id, char in session.context.characters.items():
        prev_hp = hp_before.get(char_id)
        if prev_hp is None:
            continue
        diff = prev_hp - char.status.curr_hp
        if diff > 0:
            lines.append(
                f"  {char_id.name}: -{diff} HP ({prev_hp} → {char.status.curr_hp})"
            )
        elif diff < 0:
            lines.append(
                f"  {char_id.name}: +{-diff} HP ({prev_hp} → {char.status.curr_hp})"
            )
    return lines
