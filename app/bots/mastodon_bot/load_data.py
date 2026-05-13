import json
import os

import gspread
from gspread.utils import ValueRenderOption

from battle.objects.buff.models import BuffData
from battle.objects.skill.models import SkillData
from spreadsheets.models.battle import CharacterDataFromSpreadsheet


def load_all_data() -> tuple[
    dict[str, BuffData],
    dict[str, SkillData],
    dict[str, CharacterDataFromSpreadsheet],
]:
    """
    스프레드시트에서 버프·스킬·캐릭터 데이터를 로드한다.
    반환값: (buff_dict, skill_dict, char_dict)
      - buff_dict:  버프 id → BuffData
      - skill_dict: 스킬 id → SkillData
      - char_dict:  mastodon_id → CharacterDataFromSpreadsheet
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

    char_raw = db.worksheet("캐릭터").get_all_records(value_render_option=unformatted)
    char_dict: dict[str, CharacterDataFromSpreadsheet] = {
        r["mastodon_id"]: CharacterDataFromSpreadsheet.from_dict(r)
        for r in char_raw
        if r.get("mastodon_id")
    }

    return buff_dict, skill_dict, char_dict
