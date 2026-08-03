"""load_battle_data()가 실제 스프레드시트 시트명("스킬_패시브", "버프_패시브")을
올바르게 찾아 패시브 스킬을 로드하는지에 대한 회귀 테스트.
"""

import gspread

from bot.load_data import load_battle_data
from bot.sheet_cache import SheetCache


class _FakeWorksheet:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def get_all_records(self, value_render_option=None):
        return self._rows

    def get_values(self, value_render_option=None, pad_values=True):
        if not self._rows:
            return []
        header = list(self._rows[0].keys())
        return [header] + [[row.get(h, "") for h in header] for row in self._rows]


class _FakeSpreadsheet:
    def __init__(self, sheets: dict[str, list[dict]]):
        self._sheets = {name: _FakeWorksheet(rows) for name, rows in sheets.items()}
        self.id = "fake-battle-data-spreadsheet-id"
        self.client = None
        self.fetch_sheet_metadata_call_count = 0

    def worksheet(self, name):
        if name not in self._sheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._sheets[name]

    def fetch_sheet_metadata(self):
        self.fetch_sheet_metadata_call_count += 1
        return {"sheets": [{"properties": {"title": name}} for name in self._sheets]}


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


def test_load_battle_data_shares_sheet_metadata_via_cache():
    """cache가 주어지면 "버프"/"스킬_캐릭터"/"캐릭터"/"에너미" 등 서로 다른 이름의
    시트를 9개 가까이 조회해도 fetch_sheet_metadata()는 인스턴스당 1회만 불려야
    한다 — [전투개시] 한 번에 9회 가까운 중복 메타데이터 읽기가 나던 문제의
    회귀 테스트."""
    sheets = _base_sheets(**{"에너미": [], "아이템": [], "인벤토리": []})
    spreadsheet = _FakeSpreadsheet(sheets)
    cache = SheetCache(
        spreadsheet,
        worksheet_factory=lambda properties: spreadsheet._sheets[properties["title"]],
    )

    load_battle_data(spreadsheet, cache=cache)

    assert spreadsheet.fetch_sheet_metadata_call_count == 1
