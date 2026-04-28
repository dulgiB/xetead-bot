import json
import os
from xml.dom.minidom import CharacterData

import gspread
from battle.core.battlefield_context import BattlefieldContext
from battle.objects.buff.models import BuffData
from battle.objects.define import BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillData
from dotenv import load_dotenv
from gspread.utils import ValueRenderOption
from spreadsheets.models.battle import CharacterDataFromSpreadsheet

load_dotenv()

if __name__ == "__main__":
    gc = gspread.service_account_from_dict(
        json.loads(os.environ.get("GOOGLE_SPREADSHEET_CREDENTIALS"))
    )
    db_spreadsheet = gc.open_by_key(os.environ.get("DB_SPREADSHEET_KEY"))

    buff_data_worksheet = db_spreadsheet.worksheet("버프")
    buff_raw_data_list = buff_data_worksheet.get_all_records(
        value_render_option=ValueRenderOption.unformatted
    )
    buff_data_dict: dict[str, BuffData] = {
        buff_raw_data["id"]: BuffData.from_dict(buff_raw_data)
        for buff_raw_data in buff_raw_data_list
    }

    skill_data_worksheet = db_spreadsheet.worksheet("스킬")
    skill_raw_data_list = skill_data_worksheet.get_all_records(
        value_render_option=ValueRenderOption.unformatted
    )
    skill_data_dict: dict[str, SkillData] = {
        skill_raw_data["id"]: SkillData.from_dict(skill_raw_data)
        for skill_raw_data in skill_raw_data_list
    }

    context = BattlefieldContext(buff_data_dict, skill_data_dict)

    characters_to_add = [
        ("테스트", FactionType.ALLY, BattlefieldColumnIndex(0)),
        ("에너미", FactionType.ENEMY, BattlefieldColumnIndex(0)),
    ]
    character_data_worksheet = db_spreadsheet.worksheet("캐릭터")
    character_raw_data_list = character_data_worksheet.get_all_records(
        value_render_option=ValueRenderOption.unformatted
    )
    character_data_dict: dict[str, CharacterDataFromSpreadsheet] = {
        character_raw_data["name"]: CharacterDataFromSpreadsheet.from_dict(
            character_raw_data
        )
        for character_raw_data in character_raw_data_list
        if character_raw_data["name"]
    }

    for name, faction_type, column_idx in characters_to_add:
        context.add_character(character_data_dict[name], faction_type, column_idx)

    print(context)
