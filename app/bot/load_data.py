import json
import logging
import os
from typing import TYPE_CHECKING, Optional

import gspread
from battle.objects.buff.models import BuffData, PassiveBuffData
from battle.objects.define import ActionType
from battle.objects.item.models import ItemData
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.models import SkillData
from gspread.utils import ValueRenderOption
from spreadsheets.inventory import Inventory
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet
from spreadsheets.models.quest import (
    DailyQuestPools,
    DailyQuestResultMessageData,
    QuestData,
    QuestLocationData,
)
from utils.spreadsheet_bool import parse_spreadsheet_bool

from bot.sheet_cache import SheetCache

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.commands.models import CharacterCommand

logger = logging.getLogger(__name__)

_UNFORMATTED = ValueRenderOption.unformatted


def _worksheet(
    spreadsheet: gspread.Spreadsheet, name: str, cache: Optional[SheetCache]
) -> gspread.Worksheet:
    """cache가 주어지면 그 인스턴스가 공유하는 시트 메타데이터를 재사용해
    spreadsheet.worksheet(name)의 매번 새로운 메타데이터 조회를 피한다."""
    return cache.worksheet(name) if cache is not None else spreadsheet.worksheet(name)


def load_battle_data(
    spreadsheet: gspread.Spreadsheet,
    cache: Optional[SheetCache] = None,
) -> tuple[
    dict[str, BuffData],
    dict[str, SkillData],
    dict[str, PassiveSkillData],
    dict[str, ItemData],
    Inventory,
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, NoncombatCharacterDataFromSpreadsheet],
]:
    """
    스프레드시트에서 버프·스킬·패시브 스킬·아이템·인벤토리·캐릭터 데이터를 로드한다.
    전투 세션(본 전투/대련/상시전투)을 새로 시작할 때마다 호출해 최신 데이터를 반영한다.
    반환값: (buff_dict, skill_dict, passive_skill_dict, item_dict, inventory,
             char_dict, name_dict, noncombat_char_dict)
      - buff_dict:           버프 id → BuffData
      - skill_dict:          스킬 id → SkillData
      - passive_skill_dict:  패시브 스킬 id → PassiveSkillData
      - item_dict:           아이템 id → ItemData
      - inventory:           (캐릭터 이름, 아이템 이름) → 보유 개수 (시트 write-back 포함)
      - char_dict:           mastodon_id → CombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만)
      - name_dict:           name → CombatCharacterDataFromSpreadsheet (전체)
      - noncombat_char_dict: mastodon_id → NoncombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만)

    `cache`가 주어지면(멘션 하나 처리 범위의 SheetCache) "버프"/"스킬_캐릭터"/
    "스킬_에너미"/"스킬_패시브"/"버프_패시브"/"아이템"/"인벤토리"/"캐릭터"/"에너미"
    9개 시트 조회가 시트 메타데이터를 인스턴스당 1회만 공유해서 쓴다 — 캐시가
    없으면 gspread가 이름마다 매번 전체 메타데이터를 새로 읽어온다.
    """
    db = spreadsheet

    buff_raw = _worksheet(db, "버프", cache).get_all_records(
        value_render_option=_UNFORMATTED
    )
    buff_dict: dict[str, BuffData] = {
        str(r["id"]): BuffData.from_dict(r) for r in buff_raw if r.get("id")
    }

    char_skill_raw = _worksheet(db, "스킬_캐릭터", cache).get_all_records(
        value_render_option=_UNFORMATTED
    )
    skill_dict: dict[str, SkillData] = {
        str(r["id"]): SkillData.from_dict(r) for r in char_skill_raw if r.get("id")
    }
    try:
        enemy_skill_raw = _worksheet(db, "스킬_에너미", cache).get_all_records(
            value_render_option=_UNFORMATTED
        )
        skill_dict.update(
            {
                str(r["id"]): SkillData.from_dict(r)
                for r in enemy_skill_raw
                if r.get("id")
            }
        )
    except gspread.exceptions.WorksheetNotFound:
        logger.warning(
            "'스킬_에너미' 시트를 찾을 수 없습니다. 에너미 스킬 없이 로드합니다."
        )

    passive_buff_dict = load_passive_buff_data(db, cache=cache)

    passive_skill_dict: dict[str, PassiveSkillData] = {}
    try:
        passive_skill_raw = _worksheet(db, "스킬_패시브", cache).get_all_records(
            value_render_option=_UNFORMATTED
        )
        passive_skill_dict = {
            str(r["id"]): PassiveSkillData.from_dict(r, passive_buff_dict)
            for r in passive_skill_raw
            if r.get("id")
        }
    except gspread.exceptions.WorksheetNotFound:
        logger.warning(
            "'스킬_패시브' 시트를 찾을 수 없습니다. 패시브 스킬 없이 로드합니다."
        )

    item_dict = load_item_data(db, cache=cache)
    inventory = load_inventory(db, cache=cache)

    char_dict, name_dict, noncombat_char_dict = load_char_data(db, cache=cache)

    return (
        buff_dict,
        skill_dict,
        passive_skill_dict,
        item_dict,
        inventory,
        char_dict,
        name_dict,
        noncombat_char_dict,
    )


def load_all_data() -> tuple[
    dict[str, BuffData],
    dict[str, SkillData],
    dict[str, PassiveSkillData],
    dict[str, ItemData],
    Inventory,
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, NoncombatCharacterDataFromSpreadsheet],
    gspread.Spreadsheet,
    gspread.Spreadsheet,
]:
    """
    봇 시작 시 1회 호출한다. gspread 연결을 새로 맺고 `load_battle_data()`로 위임한 뒤
    spreadsheet 핸들을 덧붙여 반환한다. 전투 세션 시작 시점의 재로드는
    `load_battle_data(state.spreadsheet)`를 직접 사용한다 (연결 재인증 불필요).

    `field_spreadsheet`는 관중에게 공개하는 실시간 전투 UI 전용 스프레드시트로,
    `db`(내부용 자동화 DB)와는 별도다.
    """
    gc = gspread.service_account_from_dict(
        json.loads(os.environ["GOOGLE_SPREADSHEET_CREDENTIALS"])
    )
    db = gc.open_by_key(os.environ["DB_SPREADSHEET_KEY"])
    field_spreadsheet = gc.open_by_key(os.environ["FIELD_SPREADSHEET_KEY"])

    return (*load_battle_data(db), db, field_spreadsheet)


def load_passive_buff_data(
    spreadsheet: gspread.Spreadsheet,
    cache: Optional[SheetCache] = None,
) -> dict[str, PassiveBuffData]:
    """'버프_패시브' 시트를 읽어 id → PassiveBuffData dict를 반환한다.

    패시브 스킬이 기존 버프 이벤트를 그대로 재사용하는 "버프 모디파이어 경로"
    전용 데이터로, 지속시간/적층 등이 없는 '버프' 시트의 축소판이다.
    """
    try:
        passive_buff_raw = _worksheet(
            spreadsheet, "버프_패시브", cache
        ).get_all_records(value_render_option=_UNFORMATTED)
    except gspread.exceptions.WorksheetNotFound:
        logger.warning(
            "'버프_패시브' 시트를 찾을 수 없습니다. 버프 모디파이어 없이 로드합니다."
        )
        return {}

    return {
        str(r["id"]): PassiveBuffData.from_dict(r)
        for r in passive_buff_raw
        if r.get("id")
    }


def load_item_data(
    spreadsheet: gspread.Spreadsheet, cache: Optional[SheetCache] = None
) -> dict[str, ItemData]:
    """'아이템' 시트를 읽어 아이템 id → ItemData dict를 반환한다."""
    try:
        item_raw = _worksheet(spreadsheet, "아이템", cache).get_all_records(
            value_render_option=_UNFORMATTED
        )
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'아이템' 시트를 찾을 수 없습니다. 아이템 없이 로드합니다.")
        return {}

    return {str(r["id"]): ItemData.from_dict(r) for r in item_raw if r.get("id")}


def load_inventory(
    spreadsheet: gspread.Spreadsheet, cache: Optional[SheetCache] = None
) -> Inventory:
    """'인벤토리' 시트를 읽어 (캐릭터 이름, 아이템 이름) → 개수 Inventory를 반환한다.

    반환하는 Inventory는 이후 소비/지급 시 write-back을 위해 spreadsheet를 직접
    들고 있다. 이 함수가 받은 `cache`는 여기서 딱 한 번의 초기 로드에만
    쓰인다 — Inventory는 전투 세션 내내 유지되는 객체라 멘션 하나 범위의
    SheetCache를 생성자에서 붙박이로 들고 있으면 다음 멘션부터 낡은
    캐시(과거 스냅샷)를 계속 재사용하는 문제가 생긴다. 그래서 Inventory는
    별도의 `cache` 속성을 두고, 실제로 그 인벤토리를 다루는 호출측이 매
    멘션마다 최신 SheetCache로 갱신한다(handle_character_command,
    handle_use_item 등 — `inventory.cache = state.sheet_cache`).
    """
    try:
        inventory_raw = _worksheet(spreadsheet, "인벤토리", cache).get_all_records(
            value_render_option=_UNFORMATTED
        )
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'인벤토리' 시트를 찾을 수 없습니다. 인벤토리 없이 로드합니다.")
        return Inventory({}, spreadsheet)

    counts: dict[tuple[str, str], int] = {
        (str(r["character_name"]), str(r["item_id"])): int(r["count"] or 0)
        for r in inventory_raw
        if r.get("character_name") and r.get("item_id")
    }
    return Inventory(counts, spreadsheet)


def load_char_data(
    spreadsheet: gspread.Spreadsheet,
    cache: Optional[SheetCache] = None,
) -> tuple[
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, NoncombatCharacterDataFromSpreadsheet],
]:
    """
    스프레드시트에서 캐릭터·에너미 데이터를 로드한다. 캐릭터 관련 커맨드가 들어올 때마다
    호출해 최신 데이터를 반영한다. 파싱에 실패하는 행(수정 중이라 일시적으로
    형식이 깨진 행 등)은 조용히 건너뛴다.

    "에너미" 시트는 "캐릭터" 시트와 달리 비전투 스테이터스·골드·일일 의뢰 컬럼이 없으므로
    NoncombatCharacterDataFromSpreadsheet/noncombat_char_dict의 대상이 되지 않는다.
    mastodon_id가 있는 에너미(계정을 가진 에너미)는 char_dict에도 등록되어 본인 계정으로
    전투 커맨드를 입력할 수 있다.

    `cache`가 주어지면(멘션 하나 처리 범위의 SheetCache) 실제 네트워크 읽기 대신
    캐시된 값을 우선 사용한다 — 같은 멘션 처리 중 write_back_changed_hp() 등이
    같은 시트를 또 읽어도 재사용된다.

    반환값: (char_dict, name_dict, noncombat_char_dict)
      - char_dict:           mastodon_id → CombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만, 캐릭터+에너미)
      - name_dict:           name → CombatCharacterDataFromSpreadsheet (전체, 캐릭터+에너미)
      - noncombat_char_dict: mastodon_id → NoncombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만, 캐릭터만)
    """
    if cache is not None:
        char_raw = cache.get_all_records("캐릭터", value_render_option=_UNFORMATTED)
    else:
        char_raw = spreadsheet.worksheet("캐릭터").get_all_records(
            value_render_option=_UNFORMATTED
        )
    char_dict: dict[str, CombatCharacterDataFromSpreadsheet] = {}
    name_dict: dict[str, CombatCharacterDataFromSpreadsheet] = {}
    noncombat_char_dict: dict[str, NoncombatCharacterDataFromSpreadsheet] = {}

    for r in char_raw:
        name = r.get("name")
        mastodon_id = r.get("mastodon_id")
        if not name and not mastodon_id:
            continue
        try:
            combat_data = CombatCharacterDataFromSpreadsheet.from_dict(r)
            noncombat_data = NoncombatCharacterDataFromSpreadsheet.from_dict(r)
        except Exception:
            logger.warning(
                "'캐릭터' 시트 행을 읽는 중 오류가 발생해 건너뜁니다: name=%s, mastodon_id=%s",
                name,
                mastodon_id,
                exc_info=True,
            )
            continue
        if mastodon_id:
            char_dict[mastodon_id] = combat_data
            noncombat_char_dict[mastodon_id] = noncombat_data
        if name:
            name_dict[name] = combat_data

    try:
        if cache is not None:
            enemy_raw = cache.get_all_records(
                "에너미", value_render_option=_UNFORMATTED
            )
        else:
            enemy_raw = spreadsheet.worksheet("에너미").get_all_records(
                value_render_option=_UNFORMATTED
            )
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'에너미' 시트를 찾을 수 없습니다. 에너미 없이 로드합니다.")
        enemy_raw = []

    for r in enemy_raw:
        name = r.get("name")
        mastodon_id = r.get("mastodon_id")
        if not name and not mastodon_id:
            continue
        try:
            combat_data = CombatCharacterDataFromSpreadsheet.from_dict(r)
        except Exception:
            logger.warning(
                "'에너미' 시트 행을 읽는 중 오류가 발생해 건너뜁니다: name=%s, mastodon_id=%s",
                name,
                mastodon_id,
                exc_info=True,
            )
            continue
        if mastodon_id:
            char_dict[mastodon_id] = combat_data
        if name:
            name_dict[name] = combat_data

    return char_dict, name_dict, noncombat_char_dict


# ---------------------------------------------------------------------------
# 비전투 시스템 동적 로드 함수 (요청마다 호출)
# ---------------------------------------------------------------------------


def load_daily_quest_pools(
    spreadsheet: gspread.Spreadsheet, cache: Optional[SheetCache] = None
) -> DailyQuestPools:
    """'일일 의뢰' 시트를 읽어 DailyQuestPools를 반환한다.

    `client_category`/`client_name`/`quest_content` 세 컬럼 쌍은 각각
    `xxx`(값), `xxx_active`(TRUE/FALSE) 쌍으로만 유효하며, 서로 다른
    컬럼 쌍끼리는 같은 행에 있어도 대응 관계가 없다 — 값이 있고
    `xxx_active`가 TRUE인 행만 각자의 풀에 담는다.
    """
    ws = _worksheet(spreadsheet, "일일 의뢰", cache)
    records = ws.get_all_records(value_render_option=_UNFORMATTED)

    def _pool(value_col: str, active_col: str) -> list[str]:
        return [
            str(r[value_col])
            for r in records
            if str(r.get(value_col, "") or "")
            and parse_spreadsheet_bool(r.get(active_col, False))
        ]

    return DailyQuestPools(
        client_categories=_pool("client_category", "client_category_active"),
        client_names=_pool("client_name", "client_name_active"),
        quest_contents=_pool("quest_content", "quest_content_active"),
    )


def load_daily_quest_result_messages(
    spreadsheet: gspread.Spreadsheet, cache: Optional[SheetCache] = None
) -> list[DailyQuestResultMessageData]:
    """'일일 의뢰 결과 메시지' 시트를 읽어 DailyQuestResultMessageData 리스트를 반환한다."""
    ws = _worksheet(spreadsheet, "일일 의뢰 결과 메시지", cache)
    records = ws.get_all_records(value_render_option=_UNFORMATTED)
    return [
        DailyQuestResultMessageData.from_dict(r) for r in records if r.get("message")
    ]


def load_general_quest_sheet(
    spreadsheet: gspread.Spreadsheet, cache: Optional[SheetCache] = None
) -> tuple[Optional[QuestLocationData], list[QuestData]]:
    """'일반 의뢰' 시트를 읽어 (활성 장소, 그 장소에 속한 의뢰 목록)을 반환한다.

    시트의 각 행은 `name`이 비어 있으면 장소 행(id=장소 이름), 채워져 있으면
    의뢰 행(id=`{장소 이름}_{type}`)이다. `active=TRUE`인 장소 행이 현재
    위치이며, 그 장소의 id를 접두사로 갖는 의뢰 행들만 반환한다. 활성 장소가
    없으면 (None, [])을 반환한다.
    """
    ws = _worksheet(spreadsheet, "일반 의뢰", cache)
    records = ws.get_all_records(value_render_option=_UNFORMATTED)

    active_location: Optional[QuestLocationData] = None
    for r in records:
        if not r.get("id") or r.get("name"):
            continue
        if parse_spreadsheet_bool(r.get("active", False)):
            active_location = QuestLocationData.from_dict(r)
            break

    if active_location is None:
        return None, []

    prefix = f"{active_location.id}_"
    quests = [
        QuestData.from_dict(r)
        for r in records
        if r.get("name") and str(r.get("id", "")).startswith(prefix)
    ]
    return active_location, quests


def update_character_gold_and_quest_date(
    spreadsheet: gspread.Spreadsheet,
    char_name: str,
    new_gold: int,
    today: str,
    cache: Optional[SheetCache] = None,
) -> None:
    """캐릭터 시트에서 해당 캐릭터 행을 찾아 gold, daily_quest_date를 갱신한다.

    "daily_quest_status_id" 컬럼이 있으면 함께 비운다 — 의뢰가 완료돼
    더 이상 판정 답글을 기다리지 않는다는 뜻이라, 봇 재기동 복원 대상에서
    빠져야 한다(update_character_daily_quest_status_id 참고). 이 컬럼은
    선택 사항이라 없는 시트에서는 조용히 건너뛴다.
    """
    ws = _worksheet(spreadsheet, "캐릭터", cache)
    values = (
        cache.get_all_values("캐릭터")
        if cache is not None
        else ws.get_values(pad_values=True)
    )
    if not values:
        raise RuntimeError("캐릭터 시트에 필수 컬럼이 없습니다: 헤더가 비어 있습니다")
    header, rows = values[0], values[1:]

    try:
        gold_col = header.index("gold") + 1
        date_col = header.index("daily_quest_date") + 1
    except ValueError as e:
        raise RuntimeError(f"캐릭터 시트에 필수 컬럼이 없습니다: {e}") from e
    status_col = (
        header.index("daily_quest_status_id") + 1
        if "daily_quest_status_id" in header
        else None
    )
    name_col = header.index("name") if "name" in header else None

    for idx, row in enumerate(rows, start=2):
        name = row[name_col] if name_col is not None and name_col < len(row) else None
        if name == char_name:
            # update_cell()은 항상 USER_ENTERED로 기록해 "YYYY-MM-DD" 형식의
            # today 값이 Sheets에 의해 날짜 타입(내부 시리얼 넘버)으로 자동
            # 변환된다. daily_quest_date는 handle_daily_quest_start()에서
            # 문자열 그대로 재비교하므로, 그 값이 날짜로 변환되면 "오늘 이미
            # 했음" 판정이 다시는 참이 되지 않아 1일 1회 제한이 무력화된다.
            # update()의 기본값 raw=True(ValueInputOption.raw)로 그대로 저장한다.
            ws.update([[new_gold]], gspread.utils.rowcol_to_a1(idx, gold_col))
            ws.update([[today]], gspread.utils.rowcol_to_a1(idx, date_col))
            if status_col is not None:
                ws.update([[""]], gspread.utils.rowcol_to_a1(idx, status_col))
            if cache is not None:
                cache.invalidate("캐릭터")
            return

    raise RuntimeError(f"캐릭터 '{char_name}'을 캐릭터 시트에서 찾을 수 없습니다.")


def update_character_daily_quest_status_id(
    spreadsheet: gspread.Spreadsheet,
    char_name: str,
    status_id: str,
    cache: Optional[SheetCache] = None,
) -> None:
    """캐릭터 시트에서 해당 캐릭터 행을 찾아 daily_quest_status_id를 갱신한다.

    [의뢰] 진행 중 봇이 판정 답글을 기다리는 게시물 ID를 저장해 두면, 봇
    재기동으로 인메모리 상태(NonCombatState.daily_quest_mid)가 사라져도
    이어서 진행할 수 있다(main()의 재기동 복원 참고). status_id=""로
    부르면 진행 중 표시를 지운다.

    "daily_quest_status_id" 컬럼 자체가 없는 시트에서는 조용히 아무 것도
    하지 않는다 — 이 컬럼은 선택 사항이라, 아직 추가하지 않은 캐릭터
    시트에서도 기존 [의뢰] 흐름 자체는(재기동 복원 없이) 그대로 동작해야
    한다.
    """
    ws = _worksheet(spreadsheet, "캐릭터", cache)
    values = (
        cache.get_all_values("캐릭터")
        if cache is not None
        else ws.get_values(pad_values=True)
    )
    if not values:
        return
    header, rows = values[0], values[1:]
    if "daily_quest_status_id" not in header:
        return
    status_col = header.index("daily_quest_status_id") + 1
    name_col = header.index("name") if "name" in header else None

    for idx, row in enumerate(rows, start=2):
        name = row[name_col] if name_col is not None and name_col < len(row) else None
        if name == char_name:
            ws.update([[status_id]], gspread.utils.rowcol_to_a1(idx, status_col))
            if cache is not None:
                cache.invalidate("캐릭터")
            return


def update_character_curr_hp(
    spreadsheet: gspread.Spreadsheet,
    char_name: str,
    new_curr_hp: int,
    cache: Optional[SheetCache] = None,
) -> None:
    """'캐릭터' 또는 '에너미' 시트에서 해당 이름의 행을 찾아 curr_hp를 갱신한다.

    전투 중 대미지/회복은 아군·에너미 구분 없이 발생하므로 두 시트를 순서대로 찾는다.
    """
    for sheet_name in ("캐릭터", "에너미"):
        try:
            ws = _worksheet(spreadsheet, sheet_name, cache)
        except gspread.exceptions.WorksheetNotFound:
            continue

        values = (
            cache.get_all_values(sheet_name)
            if cache is not None
            else ws.get_values(pad_values=True)
        )
        if not values:
            continue
        header, rows = values[0], values[1:]
        if "curr_hp" not in header or "name" not in header:
            continue
        hp_col = header.index("curr_hp") + 1
        name_col = header.index("name")

        for idx, row in enumerate(rows, start=2):
            name = row[name_col] if name_col < len(row) else None
            if name == char_name:
                ws.update_cell(idx, hp_col, new_curr_hp)
                if cache is not None:
                    cache.invalidate(sheet_name)
                return

    raise RuntimeError(
        f"캐릭터 '{char_name}'을 캐릭터/에너미 시트에서 찾을 수 없습니다."
    )


def update_quest_taken_by(
    spreadsheet: gspread.Spreadsheet,
    quest_id: str,
    taken_by: str,
    cache: Optional[SheetCache] = None,
) -> None:
    """'일반 의뢰' 시트에서 해당 quest_id 행을 찾아 taken_by를 갱신한다."""
    ws = _worksheet(spreadsheet, "일반 의뢰", cache)
    values = (
        cache.get_all_values("일반 의뢰")
        if cache is not None
        else ws.get_values(pad_values=True)
    )
    if not values:
        raise RuntimeError(
            "일반 의뢰 시트에 필수 컬럼이 없습니다: 헤더가 비어 있습니다"
        )
    header, rows = values[0], values[1:]

    try:
        id_col = header.index("id")
        taken_by_col = header.index("taken_by") + 1
    except ValueError as e:
        raise RuntimeError(f"일반 의뢰 시트에 필수 컬럼이 없습니다: {e}") from e

    for idx, row in enumerate(rows, start=2):
        row_id = row[id_col] if id_col < len(row) else None
        if row_id == quest_id:
            ws.update_cell(idx, taken_by_col, taken_by)
            if cache is not None:
                cache.invalidate("일반 의뢰")
            return

    raise RuntimeError(f"의뢰 '{quest_id}'를 일반 의뢰 시트에서 찾을 수 없습니다.")


def _load_enemy_skill_sheet(
    spreadsheet: gspread.Spreadsheet,
    cache: Optional[SheetCache] = None,
) -> Optional[tuple[gspread.Worksheet, list[str], list[list]]]:
    """'스킬_에너미' 시트의 (worksheet, header, rows)를 반환한다. 시트 자체가
    없거나 is_revealed 컬럼이 아직 추가되지 않았으면 None을 반환한다 — 이
    컬럼은 나중에 스프레드시트에 수동으로 추가되는 것을 전제하므로, 추가되기
    전에도 호출측이 조용히 넘어갈 수 있어야 한다."""
    try:
        ws = _worksheet(spreadsheet, "스킬_에너미", cache)
    except gspread.exceptions.WorksheetNotFound:
        return None

    values = (
        cache.get_all_values("스킬_에너미")
        if cache is not None
        else ws.get_values(pad_values=True)
    )
    if not values:
        return None
    header, rows = values[0], values[1:]
    if "id" not in header or "is_revealed" not in header:
        return None
    return ws, header, rows


def mark_enemy_skill_revealed(
    spreadsheet: gspread.Spreadsheet,
    skill_id: str,
    cache: Optional[SheetCache] = None,
) -> None:
    """'스킬_에너미' 시트에서 skill_id 행을 찾아 is_revealed를 TRUE로 갱신한다."""
    loaded = _load_enemy_skill_sheet(spreadsheet, cache)
    if loaded is None:
        return
    ws, header, rows = loaded
    id_col = header.index("id")
    revealed_col = header.index("is_revealed") + 1

    for idx, row in enumerate(rows, start=2):
        if id_col < len(row) and row[id_col] == skill_id:
            ws.update_cell(idx, revealed_col, True)
            if cache is not None:
                cache.invalidate("스킬_에너미")
            return


def reveal_declared_enemy_skills(
    spreadsheet: gspread.Spreadsheet,
    context: "BattlefieldContext",
    command: "CharacterCommand",
    cache: Optional[SheetCache] = None,
) -> None:
    """적이 PRE 페이즈에 선언한 커맨드에 포함된 스킬 중 아직 공개되지 않은
    것이 있으면 공개 상태로 전환한다. 같은 전투 세션 안에서 즉시 반영되도록
    `context.mark_skill_revealed()`로 skill_dict를 갱신하고, 다음 전투부터도
    공개 상태가 유지되도록 '스킬_에너미' 시트에도 write-back한다.

    호출측은 이 함수를 부르기 *전에* 이미 블라인드 상태 그대로 답글 텍스트를
    만들어 둬야 한다 — 이번 선언 자체는 블라인드로 예고되고, 다음 선언부터
    공개되는 것이 의도된 동작이다.

    한 커맨드 안에 아직 공개되지 않은 스킬이 여러 개(하이픈으로 이어붙인
    복수 스킬) 있어도 시트는 한 번만 읽는다 — 스킬마다 개별적으로 다시
    읽으면 먼저 처리한 스킬의 write-back이 캐시를 무효화해, 뒤이은 스킬마다
    캐시 미스로 시트를 통째로 재조회하는 불필요한 API 호출이 반복된다.
    """
    skill_ids_to_reveal: list[str] = []
    for part in command.parts:
        if part.type_ != ActionType.SKILL or part.skill_id is None:
            continue
        skill_data = context.get_skill_data_by_id(part.skill_id)
        if skill_data.revealed:
            continue
        context.mark_skill_revealed(part.skill_id)
        skill_ids_to_reveal.append(part.skill_id)

    if not skill_ids_to_reveal:
        return

    loaded = _load_enemy_skill_sheet(spreadsheet, cache)
    if loaded is None:
        return
    ws, header, rows = loaded
    id_col = header.index("id")
    revealed_col = header.index("is_revealed") + 1

    remaining = set(skill_ids_to_reveal)
    for idx, row in enumerate(rows, start=2):
        if not remaining:
            break
        if id_col < len(row) and row[id_col] in remaining:
            ws.update_cell(idx, revealed_col, True)
            remaining.discard(row[id_col])

    if cache is not None:
        cache.invalidate("스킬_에너미")
