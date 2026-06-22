import json
import os

import gspread
from battle.objects.buff.models import BuffData
from battle.objects.skill.models import SkillData
from gspread.utils import ValueRenderOption
from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet


def load_all_data() -> tuple[
    dict[str, BuffData],
    dict[str, SkillData],
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, CombatCharacterDataFromSpreadsheet],
    gspread.Spreadsheet,
]:
    """
    스프레드시트에서 버프·스킬·캐릭터 데이터를 로드한다.
    반환값: (buff_dict, skill_dict, char_dict, name_dict, spreadsheet)
      - buff_dict:  버프 id → BuffData
      - skill_dict: 스킬 id → SkillData
      - char_dict:  mastodon_id → CharacterDataFromSpreadsheet  (mastodon_id 있는 것만)
      - name_dict:  name → CharacterDataFromSpreadsheet         (전체)
      - spreadsheet: gspread.Spreadsheet (상태 저장용)
    """
    gc = gspread.service_account_from_dict(
        json.loads(os.environ["GOOGLE_SPREADSHEET_CREDENTIALS"])
    )
    db = gc.open_by_key(os.environ["DB_SPREADSHEET_KEY"])
    unformatted = ValueRenderOption.unformatted

    buff_raw = db.worksheet("버프").get_all_records(value_render_option=unformatted)
    buff_dict: dict[str, BuffData] = {r["id"]: BuffData.from_dict(r) for r in buff_raw}

    skill_raw = db.worksheet("스킬").get_all_records(value_render_option=unformatted)
    skill_dict: dict[str, SkillData] = {
        r["id"]: SkillData.from_dict(r) for r in skill_raw
    }

    char_dict, name_dict = load_char_data(db)

    return buff_dict, skill_dict, char_dict, name_dict, db


def load_char_data(
    spreadsheet: gspread.Spreadsheet,
) -> tuple[
    dict[str, CombatCharacterDataFromSpreadsheet],
    dict[str, CombatCharacterDataFromSpreadsheet],
]:
    """
    스프레드시트에서 캐릭터 데이터만 로드한다. BattlefieldContext 생성 직전에 호출해
    최신 데이터를 반영한다.
    반환값: (char_dict, name_dict)
      - char_dict: mastodon_id → CharacterDataFromSpreadsheet  (mastodon_id 있는 것만)
      - name_dict: name → CharacterDataFromSpreadsheet         (전체)
    """
    unformatted = ValueRenderOption.unformatted
    char_raw = spreadsheet.worksheet("캐릭터").get_all_records(
        value_render_option=unformatted
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
    return char_dict, name_dict
