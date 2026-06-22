import json
import logging
import os

import gspread
from battle.objects.buff.models import BuffData
from battle.objects.skill.models import SkillData
from gspread.utils import ValueRenderOption
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet
from spreadsheets.models.quest import (
    DailyQuestData,
    DailyQuestResultMessageData,
    QuestData,
)

logger = logging.getLogger(__name__)

_UNFORMATTED = ValueRenderOption.unformatted


def load_all_data() -> tuple[
    dict[str, BuffData],
    dict[str, SkillData],
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, NoncombatCharacterDataFromSpreadsheet],
    gspread.Spreadsheet,
]:
    """
    스프레드시트에서 버프·스킬·캐릭터 데이터를 로드한다.
    반환값: (buff_dict, skill_dict, char_dict, name_dict, noncombat_char_dict, spreadsheet)
      - buff_dict:           버프 id → BuffData
      - skill_dict:          스킬 id → SkillData
      - char_dict:           mastodon_id → CombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만)
      - name_dict:           name → CombatCharacterDataFromSpreadsheet (전체)
      - noncombat_char_dict: mastodon_id → NoncombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만)
      - spreadsheet: gspread.Spreadsheet (상태 저장 및 동적 로드용)
    """
    gc = gspread.service_account_from_dict(
        json.loads(os.environ["GOOGLE_SPREADSHEET_CREDENTIALS"])
    )
    db = gc.open_by_key(os.environ["DB_SPREADSHEET_KEY"])

    buff_raw = db.worksheet("버프").get_all_records(value_render_option=_UNFORMATTED)
    buff_dict: dict[str, BuffData] = {r["id"]: BuffData.from_dict(r) for r in buff_raw}

    skill_raw = db.worksheet("스킬").get_all_records(value_render_option=_UNFORMATTED)
    skill_dict: dict[str, SkillData] = {
        r["id"]: SkillData.from_dict(r) for r in skill_raw
    }

    char_dict, name_dict, noncombat_char_dict = load_char_data(db)

    return buff_dict, skill_dict, char_dict, name_dict, noncombat_char_dict, db


def load_char_data(
    spreadsheet: gspread.Spreadsheet,
) -> tuple[
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, NoncombatCharacterDataFromSpreadsheet],
]:
    """
    스프레드시트에서 캐릭터 데이터만 로드한다. BattlefieldContext 생성 직전에 호출해
    최신 데이터를 반영한다.
    반환값: (char_dict, name_dict, noncombat_char_dict)
      - char_dict:           mastodon_id → CombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만)
      - name_dict:           name → CombatCharacterDataFromSpreadsheet (전체)
      - noncombat_char_dict: mastodon_id → NoncombatCharacterDataFromSpreadsheet (mastodon_id 있는 것만)
    """
    char_raw = spreadsheet.worksheet("캐릭터").get_all_records(
        value_render_option=_UNFORMATTED
    )
    char_dict: dict[str, CombatCharacterDataFromSpreadsheet] = {
        r["mastodon_id"]: CombatCharacterDataFromSpreadsheet.from_dict(r)
        for r in char_raw
        if r.get("mastodon_id")
    }
    name_dict: dict[str, CombatCharacterDataFromSpreadsheet] = {
        r["name"]: CombatCharacterDataFromSpreadsheet.from_dict(r)
        for r in char_raw
        if r.get("name")
    }
    noncombat_char_dict: dict[str, NoncombatCharacterDataFromSpreadsheet] = {
        r["mastodon_id"]: NoncombatCharacterDataFromSpreadsheet.from_dict(r)
        for r in char_raw
        if r.get("mastodon_id")
    }
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
