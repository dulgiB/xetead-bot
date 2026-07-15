"""load_battle_data()가 실제 스프레드시트 시트명("스킬_패시브", "버프_패시브")을
올바르게 찾아 패시브 스킬을 로드하는지에 대한 회귀 테스트.
"""

import gspread

from bot.load_data import load_battle_data


class _FakeWorksheet:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def get_all_records(self, value_render_option=None):
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, sheets: dict[str, list[dict]]):
        self._sheets = {name: _FakeWorksheet(rows) for name, rows in sheets.items()}

    def worksheet(self, name):
        if name not in self._sheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._sheets[name]


def _base_sheets(**overrides) -> dict[str, list[dict]]:
    base = {
        "버프": [],
        "스킬_캐릭터": [],
        "캐릭터": [],
    }
    base.update(overrides)
    return base


def test_load_battle_data_finds_passive_skill_sheet_by_correct_name():
    """'패시브 스킬'이 아니라 '스킬_패시브'가 실제 시트명이다."""
    sheets = _base_sheets(
        **{
            "스킬_패시브": [
                {
                    "id": "TestPassive1",
                    "trigger": "행동 시",
                    "target_type": "자신",
                    "buff_id": "",
                    "description": "",
                }
            ]
        }
    )
    spreadsheet = _FakeSpreadsheet(sheets)

    (_buff_dict, _skill_dict, passive_skill_dict, *_rest) = load_battle_data(
        spreadsheet
    )

    assert "TestPassive1" in passive_skill_dict


def test_load_battle_data_loads_passive_buff_modifier_path():
    """'버프_패시브' 시트를 읽어 buff_id 경로(버프 모디파이어)가 정상 로드되어야 한다."""
    sheets = _base_sheets(
        **{
            "버프_패시브": [
                {
                    "id": "TestPassive2",
                    "buff_name": "BuffGivenDamage",
                    "value": 20,
                    "value_type": "퍼센트",
                    "condition": "IsInSameColumnCondition",
                    "condition_value": "",
                    "description": "",
                }
            ],
            "스킬_패시브": [
                {
                    "id": "TestPassive2",
                    "trigger": "행동 시",
                    "target_type": "자신",
                    "buff_id": "TestPassive2",
                    "description": "",
                }
            ],
        }
    )
    spreadsheet = _FakeSpreadsheet(sheets)

    (_buff_dict, _skill_dict, passive_skill_dict, *_rest) = load_battle_data(
        spreadsheet
    )

    passive = passive_skill_dict["TestPassive2"]
    assert passive.buff_mod_event is not None
    assert passive.effects == []


def test_load_battle_data_without_passive_sheets_still_loads():
    """'스킬_패시브'/'버프_패시브' 시트가 없어도 나머지 데이터는 정상 로드되어야 한다."""
    spreadsheet = _FakeSpreadsheet(_base_sheets())

    (_buff_dict, _skill_dict, passive_skill_dict, *_rest) = load_battle_data(
        spreadsheet
    )

    assert passive_skill_dict == {}
