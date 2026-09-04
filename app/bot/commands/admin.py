import logging
import random
import re
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

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
    drop_intermediate_consecutive_moves,
    escape_markdown,
    format_battle_end_log_entries,
    format_battle_reply,
    format_eliminated_characters,
    format_final_hp_roster,
    format_round_end_log_entries,
    merge_damage_heal_lines,
    merge_stackable_buff_add_lines,
)
from bot.dm_battle_state import DmBattleState
from bot.field_sheet_renderer import render_public_field_sheet
from bot.load_data import (
    find_unreachable_enemy_buffs,
    load_battle_data,
    load_enemy_skill_dict,
    reveal_declared_enemy_skills,
)
from bot.log_sheets import (
    BattleCommandLog,
    FieldBattleType,
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
_RE_FORCE_ELIMINATE = re.compile(
    rf"\[{whitespace_tolerant_literal('탈락')}\s*/\s*([^/\]]+?)]"
)
_RE_BATTLE_START = re.compile(rf"\[{whitespace_tolerant_literal('전투개시')}]")
_RE_BATTLE_NAME = re.compile(r"「(.+?)」")
_RE_PHASE = re.compile(rf"\[{whitespace_tolerant_literal('진행')}]")
_RE_CONTINUE = re.compile(rf"\[{whitespace_tolerant_literal('전투속행')}]")
_RE_END = re.compile(rf"\[{whitespace_tolerant_literal('전투종료')}]")
_RE_INVESTIGATION_BATTLE = re.compile(rf"\[{whitespace_tolerant_literal('상시전투')}]")
_RE_PRACTICE_PREP = re.compile(rf"\[{whitespace_tolerant_literal('대련')}]")
_RE_DM_BATTLE_START = re.compile(rf"\[{whitespace_tolerant_literal('전투발생')}]")
_RE_PROXY = re.compile(
    r"^\s*(?:◊\s*)?([^\[\]\n]+?)\s+(\[[^\[\]\n]+])\s*$", re.MULTILINE
)
# "[판정: 선착 1인, 55분까지]"처럼 콜론을 쓰는 안내문 표기 — 캐릭터용
# "[판정/스탯]" 커맨드(슬래시)와는 형식이 달라 실제 판정 커맨드로 오인되지
# 않는다. admin이 플레이어 안내문에 이 표기를 쓰면서 봇을 실수로 멘션해도
# "알 수 없는 관리자 커맨드입니다" 오류를 내지 않고 조용히 무시한다.
_RE_JUDGE_ANNOUNCE = re.compile(rf"\[{whitespace_tolerant_literal('판정')}\s*:[^\]]*]")


def _dm_mention_prefix(dm_state: "DmBattleState") -> str:
    """DM 전투 참가자 멘션 텍스트를 만든다. visibility="direct" 게시물은
    명시적으로 멘션된 계정만 볼 수 있으므로, 페이즈 전환/정산/종료 게시물마다
    이 프리픽스를 붙여야 참가자가 스레드를 계속 확인할 수 있다."""
    if not dm_state.mentions:
        return ""
    return " ".join(f"@{a}" for a in dm_state.mentions) + " "


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
    # 프록시 커맨드(_cmd_proxy)로 캐릭터 커맨드가 정산된 경우 로그_전투 기록용 자료
    battle_log: Optional[BattleCommandLog] = None
    # 한 메시지에 줄바꿈으로 여러 프록시 커맨드가 실려 각각 별도의
    # BattleCommandLog가 나온 경우 battle_log(단일) 대신 여기에 담는다.
    # 두 필드 모두 _persist_battle_log가 순서대로 처리한다.
    battle_logs: list[BattleCommandLog] = field(default_factory=list)
    # reply_text에서 분리된 계산식. 비어 있지 않으면 reply_text 게시 후
    # spoiler_text="계산식"을 붙인 접힌(CW) 후속 게시물로 이어 보낸다.
    calc_text: str = ""
    # True이면 game_post_text 게시 시 공개 필드 시트 이미지를 첨부한다 (라운드 시작/종료)
    attach_field_image: bool = False
    # True이면 reply_text를 답글이 아니라 타임라인의 새 게시물로 올린다 (전투 준비 공지 등)
    post_as_new_status: bool = False
    # game_post_text가 게시된 후 그 post_id를 이 DmBattleState의 active_post_id로
    # 쓰고 state.dm_battles에 등록한다 (DM 전투 전용)
    dm_battle_to_register: Optional["DmBattleState"] = None
    # set_practice_prep_from_game_post와 함께 쓰인다 — game_post_text 게시 후
    # 그 post_id를 이 PracticeBattleState의 prep_post_id로 쓰고
    # state.practices에 등록한다. 새로 만든 세션을 곧바로 state에 꽂지 않고
    # 이 필드로 넘기는 이유는, 등록 키(게시물 id)가 게시 완료 시점에야
    # 정해지기 때문이다.
    practice_to_register: Optional["PracticeBattleState"] = None
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
    # game_post_text에서 분리된 계산식. 비어 있지 않으면 game_post_text(+필드
    # 시트 이미지) 게시 후 spoiler_text="계산식"을 붙인 접힌(CW) 후속
    # 게시물로 이어 보낸다 — game_post_text 자체는 이미지와 함께 항상
    # 바로 보이는 본문으로 남겨야 하므로(개별 답글과 달리 CW로 숨기지
    # 않는다), calc_text처럼 spoiler_text에 합치지 않고 별도 게시물로 뗀다.
    game_post_calc_text: str = ""
    # game_post_calc_text를 CW 후속 게시물로 보낼 때 매 조각 앞에 붙일
    # 접두어. DM 전투(visibility="direct")는 멘션되지 않은 게시물이 참가자에게
    # 보이지 않으므로, 본문과 마찬가지로 계산식 후속 게시물에도 참가자 멘션을
    # 반복해야 한다 — 본 전투는 빈 문자열(접두어 없음)로 둔다.
    game_post_calc_prefix: str = ""
    # 비어 있지 않으면 reply_text/game_post_text와 별개로 admin에게만
    # visibility="direct" DM으로 조용히 보낸다 — 스프레드시트 설정 오류처럼
    # 플레이어에게 노출하면 안 되지만 admin은 알아야 하는 내용용.
    admin_dm_text: Optional[str] = None


def _dispatch_proxy_commands(
    text: str,
    run: Callable[[str, str], tuple[str, str, Optional[BattleCommandLog]]],
) -> Optional[AdminCommandResult]:
    """text에서 줄 단위로 "(◊ )이름 [커맨드]" 형태와 매칭되는 모든 프록시
    커맨드를 찾아 run()으로 하나씩 처리하고, 결과를 답글/계산식은 빈 줄로
    이어붙이고 battle_log는 battle_logs 리스트로 모아 하나의
    AdminCommandResult로 합친다. 매칭되는 줄이 하나도 없으면 None을
    반환해 호출측이 다음 분기로 넘어가게 한다."""
    matches = list(_RE_PROXY.finditer(text))
    if not matches:
        return None
    reply_parts = []
    calc_parts = []
    battle_logs = []
    for m in matches:
        reply_text, calc_text, battle_log = run(m.group(1).strip(), m.group(2).strip())
        reply_parts.append(reply_text)
        if calc_text:
            calc_parts.append(calc_text)
        if battle_log is not None:
            battle_logs.append(battle_log)
    return AdminCommandResult(
        "\n\n".join(reply_parts),
        battle_logs=battle_logs,
        calc_text="\n\n".join(calc_parts),
    )


def handle_admin_command(
    text: str,
    state: "BotState",
    acct: str = "",
    mentions: list[str] | None = None,
    visibility: str = "public",
    in_reply_to_id: Optional[int] = None,
) -> AdminCommandResult:
    """
    어드민 커맨드 텍스트를 파싱해 처리하고 AdminCommandResult를 반환한다.
    game_post_text가 None이 아니면 호출측에서 퍼블릭 게시물로 게시한다.

    `acct`는 이 커맨드를 입력한(멘션을 보낸) mastodon 계정 핸들이다 —
    프록시 커맨드(대신 입력)는 캐릭터 본인이 아니라 이 admin 계정이
    입력했다는 의미이므로, 로그_전투에는 캐릭터가 아닌 이 값이 기록된다.
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
            return _cmd_dm_battle_end(dm_state, state)
        if result := _dispatch_proxy_commands(
            text,
            lambda name, cmd: _cmd_dm_battle_proxy(dm_state, name, cmd, state, acct),
        ):
            return result
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

    if manual_place_matches := list(_RE_MANUAL_PLACE.finditer(text)):
        outcomes = [
            _cmd_manual_place(m.group(1).strip(), m.group(2).strip(), state)
            for m in manual_place_matches
        ]
        placed = [o.label for o in outcomes if o.ok]
        errors = [o.label for o in outcomes if not o.ok]
        reply_parts = []
        if placed:
            reply_parts.append("◊ 수동 배치: " + ", ".join(placed))
        reply_parts.extend(errors)
        return AdminCommandResult("\n".join(reply_parts))

    if force_eliminate_matches := list(_RE_FORCE_ELIMINATE.finditer(text)):
        replies = [
            _cmd_force_eliminate(m.group(1).strip(), state)
            for m in force_eliminate_matches
        ]
        return AdminCommandResult("\n".join(replies))

    if _RE_BATTLE_START.search(text):
        name_match = _RE_BATTLE_NAME.search(text)
        battle_name = name_match.group(1).strip() if name_match else None
        return _cmd_battle_start(state, battle_name)

    if _RE_PHASE.search(text):
        return _cmd_advance_phase(state)

    if _RE_CONTINUE.search(text):
        return _cmd_continue_battle(state)

    if _RE_END.search(text):
        end_reply, end_calc = _cmd_end(state)
        return AdminCommandResult(end_reply, calc_text=end_calc)

    if result := _dispatch_proxy_commands(
        text, lambda name, cmd: _cmd_proxy(name, cmd, state, acct)
    ):
        return result

    if _RE_JUDGE_ANNOUNCE.search(text):
        return AdminCommandResult("")

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


@dataclass
class _ManualPlaceOutcome:
    ok: bool
    # ok=True: "이름(진영 N열)" 형태의 짧은 라벨 — 호출측이 여러 건을 한 줄로
    # 모아 "◊ 수동 배치: A(...), B(...)"로 조립한다.
    # ok=False: 그대로 답글에 실을 완결된 "◊ ..." 오류 메시지.
    label: str


def _cmd_manual_place(
    name: str, faction_col_str: str, state: "BotState"
) -> _ManualPlaceOutcome:
    if state.session is None:
        return _ManualPlaceOutcome(
            False, "◊ 진행 중인 전투가 없습니다. 먼저 [전투 준비]를 입력하세요."
        )
    # 전투 중에는 라운드 종료(다음 라운드 대기) 페이즈에서만, [전투 속행] 입력
    # 전에 증원 배치를 허용한다 — 그 외 페이즈에서는 여전히 막는다.
    mid_battle_allowed = (
        state.session.started
        and state.session.current_phase
        == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY
    )
    if state.session.started and not mid_battle_allowed:
        return _ManualPlaceOutcome(
            False,
            "◊ 전투 중에는 라운드 종료(다음 라운드 대기) 단계에서만"
            " [전투 속행] 입력 전에 캐릭터를 배치할 수 있습니다.",
        )
    name = resolve_matching_key(name, state.name_dict.keys())
    if name not in state.name_dict:
        return _ManualPlaceOutcome(
            False, f"◊ 지정된 캐릭터({name})를 찾을 수 없습니다."
        )

    parts = faction_col_str.split()
    if len(parts) < 2:
        return _ManualPlaceOutcome(
            False,
            "◊ 캐릭터 배치는 [배치/(캐릭터 이름)/(진영) 0열] 형식을 따라야 합니다."
            " (예시: [배치/늑대/적군 3열])",
        )

    faction_str = parts[0]
    col_str = parts[1]

    try:
        faction = FactionType(faction_str)
    except ValueError:
        return _ManualPlaceOutcome(
            False,
            f"◊ 입력된 진영({faction_str})을 인식할 수 없습니다."
            " 진영은 '아군' 또는 '적군'이어야 합니다.",
        )

    try:
        column = BattlefieldColumnIndex.from_str(col_str)
    except ValueError:
        return _ManualPlaceOutcome(
            False,
            f"◊ 입력된 열({col_str})을 인식할 수 없습니다."
            " '1' 등 숫자만 입력하거나, '2열' 등 '○열' 형식을 사용해 주세요.",
        )

    label = f"{name}({faction.value} {column}열)"

    if mid_battle_allowed:
        try:
            state.session.add_character(state.name_dict[name], faction, column)
        except CommandValidationError as e:
            return _ManualPlaceOutcome(False, f"◊ {e}")

        try:
            upsert_field_row(
                state.spreadsheet,
                str(state.preparation_status_id),
                battle_type=FieldBattleType.MAIN,
                round_n=state.session.round_n,
                phase=state.session.current_phase.value,
                characters=build_field_characters(
                    state.session.context, include_hp=False
                ),
                meta={"name": state.session.name},
                cache=state.sheet_cache,
            )
        except Exception:
            _log_system_error("필드 시트 저장")

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
            _log_system_error("공개 필드 시트 실시간 갱신")

        return _ManualPlaceOutcome(True, label)

    state.pending_placements.append((name, faction, column))
    return _ManualPlaceOutcome(True, label)


def _cmd_force_eliminate(name: str, state: "BotState") -> str:
    """`[탈락/이름]` — 아군은 체력이 0이 되어도 라운드 종료 시 자동으로는
    필드에서 제거되지 않으므로(`BattlefieldContext._remove_eliminated_characters()`
    참고), admin이 명시적으로 사망/이탈 처리할 때 쓴다. 진영 제한은 두지
    않는다 — 적군을 서사적으로 조기 퇴장시키는 용도로도 쓸 수 있다."""
    if state.session is None or not state.session.started:
        return "◊ 진행 중인 전투가 없습니다."

    char_id = state.session.context.resolve_character_id(CharacterId(name))
    if char_id not in state.session.context.characters:
        return f"◊ 지정한 캐릭터({name})는 전투에 참여하고 있지 않습니다."

    removed = state.session.context.force_remove_character(char_id)

    try:
        upsert_field_row(
            state.spreadsheet,
            str(state.preparation_status_id),
            battle_type=FieldBattleType.MAIN,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            characters=build_field_characters(state.session.context, include_hp=False),
            meta={"name": state.session.name},
            cache=state.sheet_cache,
        )
    except Exception:
        _log_system_error("필드 시트 저장")

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
        _log_system_error("공개 필드 시트 실시간 갱신")

    return format_eliminated_characters(removed)


def _check_enemy_skill_timing_config(state: "BotState") -> Optional[str]:
    """'스킬_에너미' 시트에 어느 페이즈에서도 절대 부여될 수 없는 버프 부여
    효과(apply_timing/buff_add_timing이 모두 비어 있는 조합, 원인은
    find_unreachable_enemy_buffs() 참고)가 있으면 admin에게만 보낼 경고
    문구를 만든다. 반환값이 None이 아니면 _cmd_battle_start()가 전투 시작
    자체를 막는다 — 이 상태로 전투가 시작되면 그 버프가 실전에서 조용히
    빠진 채로 진행되고, 이미 배치·시작된 전투는 되돌릴 수 없어 admin이
    시트를 고쳐도 재시도가 안 되기 때문이다. 스프레드시트 데이터 오타
    문제라 공개 답글에 노출하면 안 되고(플레이어에게 내부 설정 문제를
    드러내는 셈), admin의 DM으로만 조용히 전달해야 한다 — 그래서 여기서는
    문구만 만들고 AdminCommandResult.admin_dm_text에 담아 반환한다.

    스프레드시트 접근 자체가 실패하면(네트워크 오류 등) 검증을 아예 할 수
    없다는 뜻이라, 이 실패로 전투 개시 자체를 막지는 않는다 — 예외를
    삼키고 서버 로그에만 남긴다."""
    try:
        enemy_skill_dict = load_enemy_skill_dict(
            state.spreadsheet, cache=state.sheet_cache
        )
    except Exception:
        _log_system_error("에너미 스킬 버프 타이밍 검증")
        return None

    broken = find_unreachable_enemy_buffs(enemy_skill_dict)
    if not broken:
        return None

    lines = "\n".join(f"- {skill_id}: [{buff_id}]" for skill_id, buff_id in broken)
    return (
        "◊ '스킬_에너미' 시트에 buff_add_timing이 비어 있어 어느 페이즈에도 "
        "적용되지 않는 버프 부여 효과가 있습니다. 해당 스킬의 "
        "buff_add_timing_N 컬럼을 '적 행동 선언' 또는 '적 공격 정산'으로 "
        f"채워주세요.\n{lines}"
    )


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

    # 0. 스프레드시트 설정 검증 — 배치/전투 시작을 실제로 진행하기 전에
    # 먼저 확인해야 한다. pending_placements/pending_participants를 비우거나
    # state.session.start()를 호출한 뒤에 문제를 발견하면 그 상태를 되돌릴
    # 수 없어(캐릭터가 이미 배치되고 전투가 시작된 채로) admin이 시트를
    # 고친 뒤 [전투개시]를 다시 입력해도 재시도가 되지 않는다. 여기서
    # 막으면 pending_* 값이 그대로 남아 있어 그대로 재시도할 수 있다.
    # reply_text=""(+ game_post_text 없음)면 _post_admin_result()가 공개
    # 게시물을 아예 남기지 않는다 — DM 알림만으로 충분하고, 플레이어에게는
    # "왜 전투가 시작 안 됐는지" 자체를 노출할 필요가 없다.
    admin_dm_text = _check_enemy_skill_timing_config(state)
    if admin_dm_text is not None:
        return AdminCommandResult("", admin_dm_text=admin_dm_text)

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
    # 참전 신청(pending_participants)과 수동 배치(pending_placements)는 서로
    # 독립적인 목록이라, 같은 캐릭터가 참전 신청도 하고 admin이 수동으로도
    # 배치했다면 위 1번에서 이미 배치된 캐릭터를 여기서 또 add_character()해
    # 같은 캐릭터가 두 칸을 동시에 차지하게 된다(add_character()는 기존
    # char_id 존재 여부를 확인하지 않고 새 슬롯에 추가한다) — 위 1번에서
    # 이미 배치를 마친 캐릭터는 제외한다.
    already_placed = set(state.session.context.characters.keys())
    ally_data_list = [
        state.char_dict[acct]
        for acct in state.pending_participants
        if acct in state.char_dict
        and CharacterId(state.char_dict[acct].name) not in already_placed
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
            battle_type=FieldBattleType.MAIN,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            characters=build_field_characters(state.session.context, include_hp=False),
            meta={"name": state.session.name},
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
            ensure_merged=True,
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

    game_post, game_post_calc = _make_phase_post_text(
        RoundPhaseType.ENEMY_PRE_ACTION,
        state.session.round_n,
        state.session,
        state.name_dict,
    )
    return AdminCommandResult(
        reply_text,
        game_post,
        attach_field_image=True,
        game_post_calc_text=game_post_calc,
    )


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
            battle_type=FieldBattleType.MAIN,
            round_n=state.session.round_n,
            phase=new_phase.value,
            characters=build_field_characters(state.session.context, include_hp=False),
            meta={"name": state.session.name},
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

    game_post, game_post_calc = _make_phase_post_text(
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
    return AdminCommandResult(
        reply,
        game_post,
        attach_field_image=True,
        game_post_calc_text=game_post_calc,
    )


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
            battle_type=FieldBattleType.MAIN,
            round_n=state.session.round_n,
            phase=new_phase.value,
            characters=build_field_characters(state.session.context, include_hp=False),
            meta={"name": state.session.name},
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

    game_post, game_post_calc = _make_phase_post_text(
        new_phase, state.session.round_n, state.session, state.name_dict
    )

    error_suffix = f"\n{_SYSTEM_ERROR_MESSAGE}" if system_error else ""
    reply = f"◊ 라운드 {state.session.round_n} 시작{error_suffix}"
    return AdminCommandResult(
        reply,
        game_post,
        attach_field_image=True,
        game_post_calc_text=game_post_calc,
    )


def _reset_main_battle_state(state: "BotState") -> None:
    """본 전투 세션과 그에 딸린 게시물 id/대기 목록을 모두 비운다 —
    [전투 종료]가 어느 단계에서 들어오든 남는 상태가 없어야 다음
    [전투 준비]가 "이미 진행 중인 전투가 있습니다"로 막히지 않는다."""
    state.session = None
    state.preparation_status_id = None
    state.active_phase_post_id = None
    state.pending_participants.clear()
    state.pending_placements.clear()


def _cmd_end(state: "BotState") -> tuple[str, str]:
    """반환값: (reply_text, calc_text).

    페이즈와 무관하게 언제 입력해도 동작해야 하므로, [전투 개시] 전
    (준비 단계)에도 받아 준비 상태를 취소한다 — 이 단계에서는 아직
    전장에 캐릭터도, "필드" 시트 행도 없어 정산할 대상 자체가 없으므로
    버프 훅/시트 기록 없이 상태만 되돌린다."""
    if state.session is None:
        return "◊ 진행 중인 전투가 없습니다.", ""

    if not state.session.started:
        _reset_main_battle_state(state)
        return "◊ 전투 종료 (전투 준비 취소)", ""

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
            battle_type=FieldBattleType.MAIN,
            round_n=state.session.round_n,
            phase=state.session.current_phase.value,
            characters=build_field_characters(context, include_hp=False),
            ended=True,
            meta={"name": state.session.name},
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

    _reset_main_battle_state(state)

    battle_end_body, battle_end_calc = format_battle_end_log_entries(
        context, battle_end_entries
    )
    body_blocks = [
        block for block in (format_final_hp_roster(context), battle_end_body) if block
    ]
    result = "◊ 전투 종료"
    if body_blocks:
        result += "\n\n" + "\n\n".join(body_blocks)
    if system_error:
        result += f"\n{_SYSTEM_ERROR_MESSAGE}"
    return result, battle_end_calc


def _cmd_practice_prep(
    expected_accts: list[str], state: "BotState", visibility: str = "public"
) -> AdminCommandResult:
    (
        buff_dict,
        skill_dict,
        passive_skill_dict,
        item_dict,
        _inventory,
        state.char_dict,
        state.name_dict,
        state.noncombat_char_dict,
    ) = load_battle_data(state.spreadsheet, cache=state.sheet_cache)
    context = PracticeBattlefieldContext(
        buff_dict, skill_dict, passive_skill_dict, item_dict
    )
    manager = PracticeRoundManager(context)
    ps = PracticeBattleState(
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
    return AdminCommandResult(
        "", game_post, set_practice_prep_from_game_post=True, practice_to_register=ps
    )


def _cmd_proxy(
    char_name: str, cmd_str: str, state: "BotState", acct: str = ""
) -> tuple[str, str, Optional[BattleCommandLog]]:
    """반환값: (reply_text, calc_text, battle_log_or_None). calc_text가
    비어 있지 않으면 호출측이 spoiler_text="계산식" 후속 게시물로 이어
    보낸다.

    대련/상시전투 참가자 대상 프록시는 main.py의 __dispatch()가
    _handle_practice_proxy_command()로 이 함수보다 먼저 가로채 처리한다
    (처리 직후 자동으로 다음 페이즈/라운드로 전환해야 하는데, 이 함수는
    본 전투 전용이라 그 전환 로직이 없다) — 그래서 여기 도달하는 시점엔
    이미 본 전투(state.session) 대상이라고 봐도 된다."""
    if state.session is None or not state.session.started:
        return "◊ 진행 중인 전투가 없습니다.", "", None

    char_id = state.session.context.resolve_character_id(CharacterId(char_name))
    if char_id not in state.session.context.characters:
        return (
            f"◊ 지정한 캐릭터({char_name})는 전투에 참여하고 있지 않습니다.",
            "",
            None,
        )

    field_id = str(state.preparation_status_id)
    round_n = state.session.round_n
    phase = state.session.current_phase
    is_enemy_declare = (
        state.session.context.characters[char_id].faction == FactionType.ENEMY
    )

    try:
        command = parse_character_command(char_id, cmd_str, state.session.context)
        if command is None:
            return "◊ 커맨드 형식을 인식할 수 없습니다.", "", None

        before = len(state.session.context.results)
        state.session.context.inventory.cache = state.sheet_cache
        state.session.process_command(command)
        new_results = state.session.context.results[before:]
        entries = [entry for result in new_results for entry in result.log_entries]
        write_back_changed_hp(
            state.spreadsheet, state.session.context, entries, cache=state.sheet_cache
        )

        try:
            render_public_field_sheet(
                state.field_spreadsheet,
                state.session.context,
                round_n=round_n,
                phase=phase.value,
                enemy_declared=state.session.manager.get_enemy_declared_commands(),
                battle_name=state.session.name,
                cache=state.field_sheet_cache,
            )
        except Exception:
            _log_system_error("공개 필드 시트 실시간 갱신")

        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            battle_type=FieldBattleType.MAIN,
            command_text=cmd_str,
            mastodon_id=acct,
            entries=entries,
        )
        reply_text, calc_text = _format_named_reply(
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
        return reply_text, calc_text, battle_log
    except CommandValidationError as e:
        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            battle_type=FieldBattleType.MAIN,
            command_text=cmd_str,
            mastodon_id=acct,
            error_trace=traceback.format_exc(),
        )
        return f"◊ {e}", "", battle_log


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
) -> tuple[str, str]:
    """(본문, 계산식) 튜플을 반환한다. 계산식이 없으면 두 번째 값은 빈
    문자열이다 — 호출측이 본문(+필드 시트 이미지)을 먼저 올리고, 계산식이
    있으면 그 게시물에 CW(spoiler_text="계산식") 후속 게시물로 이어 붙인다.

    필드 현황은 게시물에 첨부되는 공개 필드 시트 이미지로 표시하므로, 이
    텍스트에는 str(session.context) 보드를 중복으로 넣지 않는다."""
    if phase == RoundPhaseType.ENEMY_PRE_ACTION:
        return f"◊ [라운드 {round_n}] 적군 행동 선언", ""

    if phase == RoundPhaseType.ALLY_ACTION:
        return (
            f"◊ [라운드 {round_n}] 아군 행동\n\n"
            "이 게시물에 답글로 커맨드를 입력해 주세요."
        ), ""

    if phase == RoundPhaseType.ENEMY_POST_ACTION:
        body, calc = _format_enemy_post_action_results(
            session.context, post_action_results or {}, name_dict
        )
        return f"◊ [라운드 {round_n}] 적군 행동 정산 완료\n\n{body}", calc

    if phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
        header = f"◊ [라운드 {round_n} 종료]"
        tail = "버프/디버프 갱신 완료. [전투 속행] 또는 [전투 종료]를 입력하세요."
        round_end_body, round_end_calc = format_round_end_log_entries(
            session.context, round_end_log_entries or []
        )
        body_blocks = [
            block
            for block in (
                round_end_body,
                format_eliminated_characters(eliminated_characters or []),
            )
            if block
        ]
        if body_blocks:
            body = f"{header}\n\n{'\n\n'.join(body_blocks)}\n\n{tail}"
        else:
            body = f"{header}\n\n{tail}"
        return body, round_end_calc

    return "", ""


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


def _prefix_named_block(
    char_id: CharacterId,
    block: str,
    part_result: CommandPartProcessResult,
    name_dict: dict[str, "CombatCharacterDataFromSpreadsheet"],
    *,
    include_name_prefix: bool = True,
) -> str:
    """프록시(관리자 대행) 답글은 실제로 행동한 캐릭터가 누구인지 답글 자체만
    보고는 알 수 없으므로(직접 답글과 달리 caster에게 보내는 답글이 아님),
    헤더 앞에 이름을 붙인다. 공격/스킬로 대미지를 입은 대상이 있으면 그
    계정을 헤더 줄에 멘션해 당사자에게 알린다.

    `include_name_prefix=False`면 이름 접두어를 붙이지 않는다 — 라운드
    정산처럼 여러 캐릭터의 결과를 한 게시물에 모아 보여줄 때는, 계산식
    (CW 후속 게시물)을 펼치면 어차피 캐릭터 이름이 나오므로 본문에까지
    중복해서 붙일 필요가 없다는 판단이다. 멘션은 이름 표시 여부와 무관하게
    항상 붙인다."""
    mentions = _damaged_target_mentions(part_result, name_dict)
    header_line, sep, rest = block.partition("\n")
    if mentions:
        header_line = f"{header_line} {mentions}"
    block = header_line + sep + rest
    if not include_name_prefix:
        return block
    escaped_name = escape_markdown(char_id.name)
    if header_line.startswith(f"▹ {escaped_name} |"):
        # 이동처럼 첫 줄이 이미 "▹ {이름} | ..." 형태로 시전자 자신의
        # 이름을 보여주고 있으면, 앞에 또 이름을 붙이는 순간
        # "이름 ▹ 이름 | ..."처럼 중복된다 — 이때는 접두어를 생략한다.
        return block
    return f"{escaped_name} {block}"


def _format_named_reply(
    context: "BattlefieldContext",
    char_id: CharacterId,
    part_results: list[CommandPartProcessResult],
    name_dict: dict[str, "CombatCharacterDataFromSpreadsheet"],
    *,
    show_skill_preview: bool = False,
    include_name_prefix: bool = True,
) -> tuple[str, str]:
    """part_results를 커맨드(파트) 하나당 "{이름} 【헤더】" 블록으로 조립한
    (본문, 계산식) 튜플을 반환한다. 여러 파트가 있으면 각각 별도 블록으로
    빈 줄(\\n\\n)로 구분한다. 계산식 블록도 같은 방식으로 캐릭터 이름을
    붙여 어느 행동에 대한 계산식인지 구분할 수 있게 한다(이름 표시 여부와
    무관하게 계산식에는 항상 붙인다 — 펼쳐 봤을 때는 누구 것인지 알아야
    하므로).

    같은 대상의 대미지/회복이 여러 파트에 걸쳐 나와도 본문에는 합산된
    한 줄로만 보이게 하려고, 파트 전체 기준으로 미리 계산한 합산 결과
    (`merged_lines`)와 "이미 본문에 낸 (종류, 대상)" 기록(`emitted`)을
    `format_battle_reply()` 호출마다 공유한다 — 이 함수는 파트를 하나씩
    잘라 개별 블록으로 조립하므로, 공유하지 않으면 각 호출이 자기
    파트만 보고 따로 계산해 합산이 되지 않는다."""
    parts = drop_intermediate_consecutive_moves(part_results)
    merged_lines = {
        **merge_damage_heal_lines(context, parts),
        **merge_stackable_buff_add_lines(parts),
    }
    emitted: set[tuple[BattleLogEntryKind, str]] = set()
    body_blocks = []
    calc_blocks = []
    for part_result in parts:
        body, calc = format_battle_reply(
            context,
            char_id,
            [part_result],
            show_skill_preview=show_skill_preview,
            _merged_lines=merged_lines,
            _emitted=emitted,
        )
        if body:
            body_blocks.append(
                _prefix_named_block(
                    char_id,
                    body,
                    part_result,
                    name_dict,
                    include_name_prefix=include_name_prefix,
                )
            )
        if calc:
            calc_blocks.append(f"{escape_markdown(char_id.name)} {calc}")
    return "\n\n".join(body_blocks), "\n\n".join(calc_blocks)


def _format_enemy_post_action_results(
    context: "BattlefieldContext",
    post_action_results: dict[CharacterId, list[CommandPartProcessResult]],
    name_dict: dict[str, "CombatCharacterDataFromSpreadsheet"],
) -> tuple[str, str]:
    """ENEMY_POST_ACTION 정산 결과의 (본문, 계산식) 튜플을 반환한다.

    본문은 개별 적 커맨드별로 나누지 않고 전체를 캐릭터(대상)별로 합산한
    한 줄씩으로 조립한다 — 서로 다른 적 여러 기가 같은 아군을 각각 공격해도
    "▹ 대상 | -합계 → hp/max" 한 줄로 합쳐서 보여준다(개별 커맨드 답글의
    spoiler_text 요약과 동일한 방식). 대상 이름/버프 부여 등은 처음 등장한
    순서를 유지한다.

    계산식은 여전히 적 하나당 블록으로 나눠 어느 적의 어느 굴림인지 알 수
    있게 한다(본문과 달리 합산하지 않는다).

    이동은 PRE 선언 시점에 이미 답글로 안내되었으므로 여기서는 제외한다
    (POST 재전개 시 move_list가 빈 채로 남아 헤더만 중복 출력되는 것을 막는다)."""
    all_non_move_results: list[CommandPartProcessResult] = []
    calc_blocks = []
    for user_id, part_results in post_action_results.items():
        non_move_results = [
            r
            for r in part_results
            if r.expanded_part.original_part is None
            or r.expanded_part.original_part.type_ != ActionType.MOVE
        ]
        all_non_move_results.extend(non_move_results)
        _, calc = _format_named_reply(
            context, user_id, non_move_results, name_dict, include_name_prefix=False
        )
        if calc:
            calc_blocks.append(calc)

    # caster_id는 헤더 조립에만 쓰이는데, 헤더는 이 병합 경로(본문)에서
    # 쓰이지 않으므로(각 파트가 SKILL 예고 없이 실제 결과를 이미 갖고
    # 있어 log_entries가 항상 채워져 있다) 어떤 값이어도 결과에 영향이
    # 없다 — 여기서는 실제 값을 구할 필요가 없어 빈 id를 그대로 쓴다.
    body_text, _ = format_battle_reply(context, CharacterId(""), all_non_move_results)
    if not body_text:
        body_text = "변동 없음"
    buff_info = _format_granted_buffs_info(context, post_action_results)
    if buff_info:
        body_text = f"{body_text}\n\n{buff_info}"
    return body_text, "\n\n".join(calc_blocks)


def _format_granted_buffs_info(
    context: "BattlefieldContext",
    post_action_results: dict[CharacterId, list[CommandPartProcessResult]],
) -> str:
    """이번 정산에서 새로 부여된 버프들의 설명을 "【버프 정보】\n▹ [{버프
    이름}]: {설명}" 블록으로 모은다. 본문에는 어느 적이 부여했는지, 누구에게
    적용됐는지 나오지 않으므로("적을 어느 이름을 표시하지 않는다"는 이
    함수의 기존 방침과 같은 이유), 처음 보는 버프가 뭘 하는 버프인지
    설명해 준다. 같은 버프(buff_id)가 여러 명에게 적용돼도 설명은 한 번만
    보여준다.

    설명은 버프 인스턴스의 get_description()으로 얻는다 —
    context.get_buff_data_by_id()로 "버프" 시트를 직접 조회하면 패시브
    스킬이 부여한 버프(스킬_패시브 시트 출신)에서 KeyError가 난다."""
    descriptions: dict[str, str] = {}
    for part_results in post_action_results.values():
        for part_result in part_results:
            for entry in part_result.log_entries:
                if entry.kind != BattleLogEntryKind.BUFF_ADD or entry.buff_id is None:
                    continue
                if entry.buff_id in descriptions:
                    continue
                buff = context.get_buff_instance(
                    CharacterId(entry.target_name), entry.buff_id
                )
                if buff is None:
                    continue
                descriptions[entry.buff_id] = buff.get_description(context)
    if not descriptions:
        return ""
    lines = "\n".join(
        f"▹ [{escape_markdown(buff_id)}]: {escape_markdown(description)}"
        for buff_id, description in descriptions.items()
    )
    return f"**【버프 정보】**\n{lines}"


# ---------------------------------------------------------------------------
# 상시전투 핸들러
# ---------------------------------------------------------------------------


def _cmd_investigation_battle(
    text: str, mentions: list[str], state: "BotState", visibility: str = "public"
) -> AdminCommandResult:
    """[상시전투] 커맨드: 적군을 즉시 배치하고 아군 포지션 선언 대기 안내를 게시한다."""
    (
        buff_dict,
        skill_dict,
        passive_skill_dict,
        item_dict,
        _inventory,
        state.char_dict,
        state.name_dict,
        state.noncombat_char_dict,
    ) = load_battle_data(state.spreadsheet, cache=state.sheet_cache)
    context = PracticeBattlefieldContext(
        buff_dict, skill_dict, passive_skill_dict, item_dict
    )
    manager = PracticeRoundManager(context)
    ps = PracticeBattleState(
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

    return AdminCommandResult(
        "", game_post, set_practice_prep_from_game_post=True, practice_to_register=ps
    )


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

    mention_prefix = _dm_mention_prefix(dm_state)
    phase_body, phase_calc = _make_phase_post_text(
        RoundPhaseType.ENEMY_PRE_ACTION, session.round_n, session, state.name_dict
    )
    game_post = f"{mention_prefix}{phase_body}\n\n{session.context}"
    if errors:
        game_post += "\n\n⚠️ 오류:\n" + "\n".join(errors)

    return AdminCommandResult(
        "",
        game_post,
        dm_battle_to_register=dm_state,
        game_post_calc_text=phase_calc,
        game_post_calc_prefix=mention_prefix,
    )


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
        end_body, end_calc = _end_dm_battle(dm_state, state, winner)
        mention_prefix = _dm_mention_prefix(dm_state)
        return AdminCommandResult(
            "◊ 페이즈 전환 처리 완료",
            f"{mention_prefix}{end_body}",
            game_post_reply_to_confirmation=True,
            game_post_visibility=dm_state.visibility,
            game_post_calc_text=end_calc,
            game_post_calc_prefix=mention_prefix,
        )

    mention_prefix = _dm_mention_prefix(dm_state)
    phase_body, phase_calc = _make_phase_post_text(
        new_phase,
        session.round_n,
        session,
        state.name_dict,
        post_action_results,
        round_end_log_entries,
        eliminated_characters,
    )
    game_post = f"{mention_prefix}{phase_body}\n\n{session.context}"

    return AdminCommandResult(
        f"◊ 페이즈 전환: {new_phase.value}",
        game_post,
        dm_battle_to_register=dm_state,
        game_post_reply_to_confirmation=True,
        game_post_visibility=dm_state.visibility,
        game_post_calc_text=phase_calc,
        game_post_calc_prefix=mention_prefix,
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
    mention_prefix = _dm_mention_prefix(dm_state)
    phase_body, phase_calc = _make_phase_post_text(
        new_phase, session.round_n, session, state.name_dict
    )
    game_post = f"{mention_prefix}{phase_body}\n\n{session.context}"

    return AdminCommandResult(
        f"◊ 라운드 {session.round_n} 시작",
        game_post,
        dm_battle_to_register=dm_state,
        game_post_reply_to_confirmation=True,
        game_post_visibility=dm_state.visibility,
        game_post_calc_text=phase_calc,
        game_post_calc_prefix=mention_prefix,
    )


def _cmd_dm_battle_end(
    dm_state: DmBattleState, state: "BotState"
) -> AdminCommandResult:
    """관리자가 [전투종료]로 강제 종료한다 — 전멸 시 자동 종료의 안전장치."""
    end_body, end_calc = _end_dm_battle(dm_state, state, winner=None)
    mention_prefix = _dm_mention_prefix(dm_state)
    return AdminCommandResult(
        "",
        f"{mention_prefix}{end_body}",
        game_post_visibility=dm_state.visibility,
        game_post_calc_text=end_calc,
        game_post_calc_prefix=mention_prefix,
    )


def _cmd_dm_battle_proxy(
    dm_state: DmBattleState,
    char_name: str,
    cmd_str: str,
    state: "BotState",
    acct: str = "",
) -> tuple[str, str, Optional[BattleCommandLog]]:
    """반환값: (reply_text, calc_text, battle_log_or_None)."""
    session = dm_state.session
    char_id = session.context.resolve_character_id(CharacterId(char_name))
    if char_id not in session.context.characters:
        return (
            f"◊ 지정한 캐릭터({char_name})는 전투에 참여하고 있지 않습니다.",
            "",
            None,
        )

    field_id = dm_state.field_id
    round_n = session.round_n
    phase = session.current_phase
    is_enemy_declare = session.context.characters[char_id].faction == FactionType.ENEMY

    try:
        command = parse_character_command(char_id, cmd_str, session.context)
        if command is None:
            return "◊ 커맨드 형식을 인식할 수 없습니다.", "", None

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
            battle_type=FieldBattleType.DM,
            command_text=cmd_str,
            mastodon_id=acct,
            entries=entries,
        )
        reply_text, calc_text = _format_named_reply(
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
        return f"{reply_text}\n\n{session.context}", calc_text, battle_log
    except CommandValidationError as e:
        battle_log = BattleCommandLog(
            field_id=field_id,
            round_n=round_n,
            phase=phase.value,
            battle_type=FieldBattleType.DM,
            command_text=cmd_str,
            mastodon_id=acct,
            error_trace=traceback.format_exc(),
        )
        return f"◊ {e}\n\n{session.context}", "", battle_log


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
) -> tuple[str, str]:
    """DM 전투를 종료 처리한다(전멸 자동 종료/관리자 수동 종료 공용).

    본 전투의 _cmd_end와 동일하게 전투 종료 시점 버프 훅([재앙] 등) 처리 후
    변경된 HP를 "캐릭터" 시트에 반영하고, state.dm_battles에서 이 세션을
    제거한다. 반환값은 (본문, 계산식) — DM 참가자 멘션 접두어는 이 함수가
    아니라 호출측이 붙인다(계산식 CW 후속 게시물에도 반복해서 붙여야
    하므로 한 곳에서 관리한다)."""
    session = dm_state.session
    battle_end_entries = session.context.on_battle_end()
    if battle_end_entries:
        write_back_changed_hp(
            state.spreadsheet,
            session.context,
            battle_end_entries,
            cache=state.sheet_cache,
        )

    if dm_state.field_id:
        try:
            upsert_field_row(
                state.spreadsheet,
                dm_state.field_id,
                battle_type=FieldBattleType.DM,
                round_n=session.round_n,
                phase=session.current_phase.value,
                characters=build_field_characters(session.context, include_hp=False),
                ended=True,
                meta={
                    "active_post_id": dm_state.active_post_id,
                    "visibility": dm_state.visibility,
                },
                cache=state.sheet_cache,
            )
        except Exception:
            _log_system_error("필드 시트 저장")

    state.dm_battles.pop(dm_state.active_post_id, None)

    result = f"◊ 전투 종료 (라운드 {session.round_n})"
    if winner is not None:
        result += f"\n\n승자: {winner.value}"

    battle_end_body, battle_end_calc = format_battle_end_log_entries(
        session.context, battle_end_entries
    )
    body_blocks = [
        block
        for block in (format_final_hp_roster(session.context), battle_end_body)
        if block
    ]
    if body_blocks:
        result += "\n\n" + "\n\n".join(body_blocks)
    return result, battle_end_calc


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


def find_practice_by_field_id(
    state: "BotState", field_id: str
) -> Optional[PracticeBattleState]:
    """field_id(전투 개시 게시물 id 고정 값)로 진행 중인 PracticeBattleState를
    찾는다. state.practices는 진행 게시물(tip) id(페이즈 전환마다 바뀜)를
    키로 쓰므로, find_dm_battle_by_field_id와 동일한 이유로 값들을 선형
    탐색해야 한다."""
    return next(
        (ps for ps in state.practices.values() if ps.field_id == field_id), None
    )
