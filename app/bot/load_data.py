import json
import logging
import os

import gspread
from battle.objects.buff.models import BuffData
from battle.objects.item.models import ItemData
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.models import SkillData
from gspread.utils import ValueRenderOption
from spreadsheets.inventory import Inventory
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet
from spreadsheets.models.quest import (
    DailyQuestData,
    DailyQuestResultMessageData,
    QuestData,
)

logger = logging.getLogger(__name__)

_UNFORMATTED = ValueRenderOption.unformatted


def load_battle_data(
    spreadsheet: gspread.Spreadsheet,
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
    """
    db = spreadsheet

    buff_raw = db.worksheet("버프").get_all_records(value_render_option=_UNFORMATTED)
    buff_dict: dict[str, BuffData] = {r["id"]: BuffData.from_dict(r) for r in buff_raw}

    char_skill_raw = db.worksheet("스킬_캐릭터").get_all_records(
        value_render_option=_UNFORMATTED
    )
    skill_dict: dict[str, SkillData] = {
        r["id"]: SkillData.from_dict(r) for r in char_skill_raw
    }
    try:
        enemy_skill_raw = db.worksheet("스킬_에너미").get_all_records(
            value_render_option=_UNFORMATTED
        )
        skill_dict.update({r["id"]: SkillData.from_dict(r) for r in enemy_skill_raw})
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'스킬_에너미' 시트를 찾을 수 없습니다. 에너미 스킬 없이 로드합니다.")

    passive_skill_dict: dict[str, PassiveSkillData] = {}
    try:
        passive_skill_raw = db.worksheet("패시브 스킬").get_all_records(
            value_render_option=_UNFORMATTED
        )
        passive_skill_dict = {
            r["id"]: PassiveSkillData.from_dict(r)
            for r in passive_skill_raw
            if r.get("id")
        }
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'패시브 스킬' 시트를 찾을 수 없습니다. 패시브 스킬 없이 로드합니다.")

    item_dict = load_item_data(db)
    inventory = load_inventory(db)

    char_dict, name_dict, noncombat_char_dict = load_char_data(db)

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
]:
    """
    봇 시작 시 1회 호출한다. gspread 연결을 새로 맺고 `load_battle_data()`로 위임한 뒤
    spreadsheet 핸들을 덧붙여 반환한다. 전투 세션 시작 시점의 재로드는
    `load_battle_data(state.spreadsheet)`를 직접 사용한다 (연결 재인증 불필요).
    """
    gc = gspread.service_account_from_dict(
        json.loads(os.environ["GOOGLE_SPREADSHEET_CREDENTIALS"])
    )
    db = gc.open_by_key(os.environ["DB_SPREADSHEET_KEY"])

    return (*load_battle_data(db), db)


def load_item_data(spreadsheet: gspread.Spreadsheet) -> dict[str, ItemData]:
    """'아이템' 시트를 읽어 아이템 id → ItemData dict를 반환한다."""
    try:
        item_raw = spreadsheet.worksheet("아이템").get_all_records(
            value_render_option=_UNFORMATTED
        )
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'아이템' 시트를 찾을 수 없습니다. 아이템 없이 로드합니다.")
        return {}

    return {r["id"]: ItemData.from_dict(r) for r in item_raw if r.get("id")}


def load_inventory(spreadsheet: gspread.Spreadsheet) -> Inventory:
    """'인벤토리' 시트를 읽어 (캐릭터 이름, 아이템 이름) → 개수 Inventory를 반환한다."""
    try:
        inventory_raw = spreadsheet.worksheet("인벤토리").get_all_records(
            value_render_option=_UNFORMATTED
        )
    except gspread.exceptions.WorksheetNotFound:
        logger.warning("'인벤토리' 시트를 찾을 수 없습니다. 인벤토리 없이 로드합니다.")
        return Inventory({}, spreadsheet)

    counts: dict[tuple[str, str], int] = {
        (r["character_name"], r["item_id"]): int(r["count"] or 0)
        for r in inventory_raw
        if r.get("character_name") and r.get("item_id")
    }
    return Inventory(counts, spreadsheet)


def load_char_data(
    spreadsheet: gspread.Spreadsheet,
) -> tuple[
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, NoncombatCharacterDataFromSpreadsheet],
]:
    """
    스프레드시트에서 캐릭터 데이터만 로드한다. 캐릭터 관련 커맨드가 들어올 때마다
    호출해 최신 데이터를 반영한다. 파싱에 실패하는 행(수정 중이라 일시적으로
    형식이 깨진 행 등)은 조용히 건너뛴다.
    반환값: (char_dict, name_dict, noncombat_char_dict)
      - char_dict:           mastodon_id → CombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만)
      - name_dict:           name → CombatCharacterDataFromSpreadsheet (전체)
      - noncombat_char_dict: mastodon_id → NoncombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만)
    """
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

    return char_dict, name_dict, noncombat_char_dict


# ---------------------------------------------------------------------------
# 비전투 시스템 동적 로드 함수 (요청마다 호출)
# ---------------------------------------------------------------------------


def load_daily_quests(spreadsheet: gspread.Spreadsheet) -> list[DailyQuestData]:
    """'일일 의뢰' 시트를 읽어 DailyQuestData 리스트를 반환한다."""
    ws = spreadsheet.worksheet("일일 의뢰")
    records = ws.get_all_records(value_render_option=_UNFORMATTED)
    return [DailyQuestData.from_dict(r) for r in records if r.get("id")]


def load_daily_quest_result_messages(
    spreadsheet: gspread.Spreadsheet,
) -> list[DailyQuestResultMessageData]:
    """'일일 의뢰 결과 메시지' 시트를 읽어 DailyQuestResultMessageData 리스트를 반환한다."""
    ws = spreadsheet.worksheet("일일 의뢰 결과 메시지")
    records = ws.get_all_records(value_render_option=_UNFORMATTED)
    return [
        DailyQuestResultMessageData.from_dict(r) for r in records if r.get("message")
    ]


def load_general_quests(spreadsheet: gspread.Spreadsheet) -> list[QuestData]:
    """'일반 의뢰' 시트를 읽어 QuestData 리스트를 반환한다."""
    ws = spreadsheet.worksheet("일반 의뢰")
    records = ws.get_all_records(value_render_option=_UNFORMATTED)
    return [QuestData.from_dict(r) for r in records if r.get("id")]


def load_location_and_investigation(
    spreadsheet: gspread.Spreadsheet,
) -> tuple[str, bool, list[str], dict[str, str]]:
    """'현위치' 시트(1행)에서 (현재_위치, 상시조사_활성, [venue1..3], {venue→지문}) 반환.

    현위치 시트 컬럼:
      location | investigation_active
      venue_1 | venue_1_desc | venue_2 | venue_2_desc | venue_3 | venue_3_desc
    """
    ws = spreadsheet.worksheet("현위치")
    records = ws.get_all_records(value_render_option=_UNFORMATTED)
    if not records:
        return "", False, [], {}

    row = records[0]
    location = str(row.get("location", "") or "")
    investigation_active = bool(row.get("investigation_active", False))
    venue_pairs = [
        (str(row.get("venue_1", "") or ""), str(row.get("venue_1_desc", "") or "")),
        (str(row.get("venue_2", "") or ""), str(row.get("venue_2_desc", "") or "")),
        (str(row.get("venue_3", "") or ""), str(row.get("venue_3_desc", "") or "")),
    ]
    venues = [v for v, _ in venue_pairs if v]
    venue_desc = {v: d for v, d in venue_pairs if v}
    return location, investigation_active, venues, venue_desc


def update_character_gold_and_quest_date(
    spreadsheet: gspread.Spreadsheet,
    char_name: str,
    new_gold: int,
    today: str,
) -> None:
    """캐릭터 시트에서 해당 캐릭터 행을 찾아 gold, daily_quest_date를 갱신한다."""
    ws = spreadsheet.worksheet("캐릭터")
    records = ws.get_all_records()
    header = ws.row_values(1)

    try:
        gold_col = header.index("gold") + 1
        date_col = header.index("daily_quest_date") + 1
    except ValueError as e:
        raise RuntimeError(f"캐릭터 시트에 필수 컬럼이 없습니다: {e}") from e

    for idx, row in enumerate(records, start=2):
        if row.get("name") == char_name:
            ws.update_cell(idx, gold_col, new_gold)
            ws.update_cell(idx, date_col, today)
            return

    raise RuntimeError(f"캐릭터 '{char_name}'을 캐릭터 시트에서 찾을 수 없습니다.")


def update_character_curr_hp(
    spreadsheet: gspread.Spreadsheet,
    char_name: str,
    new_curr_hp: int,
) -> None:
    """캐릭터 시트에서 해당 캐릭터 행을 찾아 curr_hp를 갱신한다."""
    ws = spreadsheet.worksheet("캐릭터")
    records = ws.get_all_records()
    header = ws.row_values(1)

    try:
        hp_col = header.index("curr_hp") + 1
    except ValueError as e:
        raise RuntimeError(f"캐릭터 시트에 필수 컬럼이 없습니다: {e}") from e

    for idx, row in enumerate(records, start=2):
        if row.get("name") == char_name:
            ws.update_cell(idx, hp_col, new_curr_hp)
            return

    raise RuntimeError(f"캐릭터 '{char_name}'을 캐릭터 시트에서 찾을 수 없습니다.")
