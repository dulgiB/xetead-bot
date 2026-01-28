import json
import os

import gspread
from battle.objects.buff.models import BuffData
from battle.objects.skill.models import SkillData
from gspread.utils import ValueRenderOption


def load_spreadsheet_data() -> tuple[dict[str, BuffData], dict[str, SkillData]]:
    gc = gspread.service_account_from_dict(
        json.loads(os.environ["GOOGLE_SPREADSHEET_CREDENTIALS"])
    )
    db = gc.open_by_key(os.environ["DB_SPREADSHEET_KEY"])

    buff_raw = db.worksheet("버프").get_all_records(
        value_render_option=ValueRenderOption.unformatted
    )
    buff_dict: dict[str, BuffData] = {r["id"]: BuffData.from_dict(r) for r in buff_raw}

    skill_raw = db.worksheet("스킬").get_all_records(
        value_render_option=ValueRenderOption.unformatted
    )
    skill_dict: dict[str, SkillData] = {
        r["id"]: SkillData.from_dict(r) for r in skill_raw
    }

    return buff_dict, skill_dict
