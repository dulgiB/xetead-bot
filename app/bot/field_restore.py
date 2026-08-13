"""봇 재기동(크래시/재배포) 시 "필드" 시트에서 ended_at이 비어 있는 전투를
찾아 BotState에 재구성한다.

메모리에만 존재하던 BotState.session/practice/dm_battles는 프로세스가
재시작되면 통째로 사라진다 — 이 모듈은 그 상태를 최대한 되살리되, 다음은
복원 대상이 아니다:

- 버프/디버프, 스킬 사용 이력, 인벤토리 소비 내역: 캐릭터 시트의 최신 상태를
  그대로 신뢰한다(요구사항: 재기동 시점의 값 우선).
- 소환수(동료): "캐릭터"/"에너미" 시트에 행이 없어 이름만으로 원본 스탯을
  다시 불러올 수 없다. 조용히 건너뛴다 — 필요하면 아군이 다시 소환한다.
- 적이 PRE_ACTION에 선언했지만 아직 POST_ACTION에서 정산되지 않은 커맨드:
  RoundManager 인스턴스에만 존재했던 정보라 애초에 스냅샷 대상이 아니다.
  크래시가 정확히 이 구간에서 나면 적이 다시 선언해야 한다.
"""

import logging
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.exceptions import CommandValidationError
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import PracticeRoundPhase, SideType
from battle.practice.round_manager import PracticeRoundManager

from bot.dm_battle_state import DmBattleState
from bot.log_sheets import FieldBattleType, FieldRow, load_open_battle_rows
from bot.practice_state import PracticeBattleState
from bot.session import BattleSession

if TYPE_CHECKING:
    from bot.main import BotState

logger = logging.getLogger(__name__)


def restore_all(
    state: "BotState",
    buff_dict: dict,
    skill_dict: dict,
    passive_skill_dict: dict,
    item_dict: dict,
    inventory,
) -> list[str]:
    """ "필드" 시트에서 미종료 전투를 찾아 state에 복원하고, 복원된 전투를
    사람이 읽을 수 있는 한 줄 요약 리스트로 반환한다(admin DM 알림용).
    시트 자체를 못 읽거나 열린 전투가 없으면 빈 리스트를 반환한다."""
    try:
        rows = load_open_battle_rows(state.spreadsheet)
    except Exception:
        logger.exception("'필드' 시트에서 복원 대상 조회 실패")
        return []

    summaries: list[str] = []
    for row in rows:
        try:
            if row.battle_type == FieldBattleType.MAIN:
                summary = _restore_main_battle(
                    state,
                    row,
                    buff_dict,
                    skill_dict,
                    passive_skill_dict,
                    item_dict,
                    inventory,
                )
            elif row.battle_type == FieldBattleType.DM:
                summary = _restore_dm_battle(
                    state,
                    row,
                    buff_dict,
                    skill_dict,
                    passive_skill_dict,
                    item_dict,
                    inventory,
                )
            else:
                summary = _restore_practice_battle(
                    state, row, buff_dict, skill_dict, passive_skill_dict, item_dict
                )
        except Exception:
            logger.exception(
                "전투 복원 실패: field_id=%s battle_type=%s",
                row.field_id,
                row.battle_type.value,
            )
            continue
        if summary is not None:
            summaries.append(summary)
    return summaries


def _restore_characters_full(
    session: "BattleSession", state: "BotState", characters: list[dict]
) -> int:
    """본 전투/DM 전투 캐릭터 스냅샷을 순서대로 재배치한다. 이름을 못
    찾으면(동료) 건너뛰고, 시트 상 이미 사망 처리된 캐릭터는
    add_character()가 거부하므로 그 역시 건너뛴다(라운드 종료 시 필드에서
    자동 제거된 캐릭터를 다시 살려내지 않기 위한 기존 동작과 일관됨).
    반환값: 실제로 복원된 캐릭터 수."""
    restored = 0
    for entry in characters:
        name = entry.get("name", "")
        data = state.name_dict.get(name)
        if data is None:
            logger.warning(
                "'%s'을(를) 캐릭터/에너미 시트에서 찾을 수 없어 복원에서 "
                "건너뜁니다(소환수이거나 시트에서 삭제된 캐릭터일 수 있습니다)",
                name,
            )
            continue
        try:
            faction = FactionType(entry["faction"])
            column = BattlefieldColumnIndex.from_str(str(entry["position"]))
            session.add_character(data, faction, column)
        except (CommandValidationError, ValueError, KeyError) as e:
            logger.warning("'%s' 복원 실패, 건너뜁니다: %s", name, e)
            continue
        char = session.context.characters.get(CharacterId(data.name))
        if char is not None and "remaining_cost" in entry:
            char.status.remaining_cost = entry["remaining_cost"]
        restored += 1
    return restored


def _restore_main_battle(
    state: "BotState",
    row: FieldRow,
    buff_dict: dict,
    skill_dict: dict,
    passive_skill_dict: dict,
    item_dict: dict,
    inventory,
) -> Optional[str]:
    try:
        phase = RoundPhaseType(row.phase)
    except ValueError:
        logger.warning(
            "본 전투 복원 실패: 알 수 없는 phase=%s (field_id=%s)",
            row.phase,
            row.field_id,
        )
        return None

    session = BattleSession(
        buff_dict, skill_dict, passive_skill_dict, item_dict, inventory
    )
    restored = _restore_characters_full(session, state, row.characters)
    if restored == 0:
        logger.warning(
            "본 전투 복원 실패: 복원 가능한 캐릭터가 없습니다 (field_id=%s)",
            row.field_id,
        )
        return None

    session.context.on_battle_start()
    session.restore_progress(row.round_n, phase)
    session.name = row.meta.get("name")

    state.session = session
    state.preparation_status_id = int(row.field_id)
    state.active_phase_post_id = row.meta.get("active_phase_post_id")

    name_label = session.name or "(이름 없음)"
    return (
        f"본전투 「{name_label}」 {row.round_n}라운드 {phase.value} — "
        f"캐릭터 {restored}명 복원 (field_id={row.field_id})"
    )


def _restore_dm_battle(
    state: "BotState",
    row: FieldRow,
    buff_dict: dict,
    skill_dict: dict,
    passive_skill_dict: dict,
    item_dict: dict,
    inventory,
) -> Optional[str]:
    try:
        phase = RoundPhaseType(row.phase)
    except ValueError:
        logger.warning(
            "DM 전투 복원 실패: 알 수 없는 phase=%s (field_id=%s)",
            row.phase,
            row.field_id,
        )
        return None

    active_post_id = row.meta.get("active_post_id")
    if active_post_id is None:
        logger.warning(
            "DM 전투 복원 실패: active_post_id 메타가 없습니다 (field_id=%s)",
            row.field_id,
        )
        return None

    session = BattleSession(
        buff_dict, skill_dict, passive_skill_dict, item_dict, inventory
    )
    restored = _restore_characters_full(session, state, row.characters)
    if restored == 0:
        logger.warning(
            "DM 전투 복원 실패: 복원 가능한 캐릭터가 없습니다 (field_id=%s)",
            row.field_id,
        )
        return None

    session.context.on_battle_start()
    session.restore_progress(row.round_n, phase)

    dm_state = DmBattleState(
        session=session,
        field_id=row.field_id,
        active_post_id=active_post_id,
        visibility=row.meta.get("visibility", "direct"),
    )
    state.dm_battles[active_post_id] = dm_state

    return (
        f"DM전투 {row.round_n}라운드 {phase.value} — "
        f"캐릭터 {restored}명 복원 (field_id={row.field_id})"
    )


def _restore_practice_battle(
    state: "BotState",
    row: FieldRow,
    buff_dict: dict,
    skill_dict: dict,
    passive_skill_dict: dict,
    item_dict: dict,
) -> Optional[str]:
    if state.practice is not None:
        logger.warning(
            "대련/상시전투 복원 건너뜀: 이미 다른 대련/상시전투를 복원했습니다 (field_id=%s)",
            row.field_id,
        )
        return None
    try:
        phase = PracticeRoundPhase(row.phase)
    except ValueError:
        logger.warning(
            "대련/상시전투 복원 실패: 알 수 없는 phase=%s (field_id=%s)",
            row.phase,
            row.field_id,
        )
        return None

    meta = row.meta
    first_mover_str = meta.get("first_mover")
    second_mover_str = meta.get("second_mover")
    if not first_mover_str or not second_mover_str:
        logger.warning(
            "대련/상시전투 복원 실패: 선공/후공 메타가 없습니다 (field_id=%s)",
            row.field_id,
        )
        return None
    try:
        first_mover = SideType(first_mover_str)
        second_mover = SideType(second_mover_str)
    except ValueError:
        logger.warning(
            "대련/상시전투 복원 실패: 선공/후공 값을 인식할 수 없습니다 (field_id=%s)",
            row.field_id,
        )
        return None

    context = PracticeBattlefieldContext(
        buff_dict, skill_dict, passive_skill_dict, item_dict
    )
    manager = PracticeRoundManager(context)

    restored = 0
    for entry in row.characters:
        name = entry.get("name", "")
        data = state.name_dict.get(name)
        if data is None:
            logger.warning(
                "'%s'을(를) 캐릭터/에너미 시트에서 찾을 수 없어 복원에서 건너뜁니다",
                name,
            )
            continue
        try:
            faction = FactionType(entry["faction"])
            side = SideType.SIDE_1 if faction == FactionType.ALLY else SideType.SIDE_2
            column = BattlefieldColumnIndex.from_str(str(entry["position"]))
            context.add_character(data, side, column)
        except (CommandValidationError, ValueError, KeyError) as e:
            logger.warning("'%s' 복원 실패, 건너뜁니다: %s", name, e)
            continue
        char = context.characters.get(CharacterId(data.name))
        if char is not None:
            if "remaining_cost" in entry:
                char.status.remaining_cost = entry["remaining_cost"]
            if "curr_hp" in entry:
                char.status.curr_hp = entry["curr_hp"]
        restored += 1

    if restored == 0:
        logger.warning(
            "대련/상시전투 복원 실패: 복원 가능한 캐릭터가 없습니다 (field_id=%s)",
            row.field_id,
        )
        return None

    manager.set_phase_for_restore(phase, first_mover, second_mover)

    ps = PracticeBattleState(
        context=context,
        manager=manager,
        round_n=row.round_n,
        round_limit=meta.get("round_limit", 3),
        # 대련/상시전투는 라운드가 시작된 뒤로는 항상 prep_post_id=0(포지션
        # 선언 접수 종료 표시)이다 — "필드" 행 자체가 start_round() 이후에만
        # 만들어지므로, 복원 대상 행이 존재한다는 것 자체가 이미 이 단계를
        # 지났다는 뜻이다. row.field_id는 시트에서 이 행을 찾는 키였을 뿐,
        # 여기 그대로 쓰면 준비 단계로 잘못 되돌아간다.
        prep_post_id=0,
        active_post_id=meta.get("active_post_id"),
        visibility=meta.get("visibility", "public"),
        first_mover=first_mover,
        second_mover=second_mover,
        is_investigation=(row.battle_type == FieldBattleType.INVESTIGATION),
    )
    state.practice = ps

    battle_label = "상시전투" if ps.is_investigation else "대련"
    return (
        f"{battle_label} {row.round_n}라운드 {phase.value} — "
        f"캐릭터 {restored}명 복원 (field_id={row.field_id})"
    )
