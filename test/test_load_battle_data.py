"""load_battle_data()가 실제 스프레드시트 시트명("스킬_패시브", "버프_패시브")을
올바르게 찾아 패시브 스킬을 로드하는지에 대한 회귀 테스트.
"""

import gspread

from bot.load_data import find_unreachable_enemy_buffs, load_battle_data
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


def test_load_battle_data_skips_blank_padding_rows_without_crashing():
    """ "버프"/"스킬_캐릭터"/"스킬_에너미" 시트에는 앞으로 데이터를 채울 여백으로
    남겨둔, id를 포함한 모든 칸이 빈 문자열인 행이 섞여 있을 수 있다.
    SkillData.from_dict()의 target_count/cost는 int(data[...])로 캐스팅해
    빈 문자열이면 그대로 ValueError로 죽는데, id 없는 행을 걸러내지 않고
    전부 순회하면 실제 스킬을 하나도 정의하지 않은 시트라도 봇이 시작하지
    못한다. id가 있는 행만 읽어 나머지 유효한 데이터는 정상 로드되어야
    한다."""
    blank_row = {
        "id": "",
        "buff_name": "",
        "duration_turn_value": "",
        "duration_count_value": "",
        "duration_count_deduct_condition": "",
        "value_type": "",
        "value": "",
        "condition": "",
        "condition_value": "",
        "description": "",
    }
    blank_skill_row = {
        "id": "",
        "target_rule": "",
        "target_count": "",
        "cost": "",
        "description": "",
    }
    sheets = _base_sheets(
        **{
            "버프": [blank_row, blank_row],
            "스킬_캐릭터": [
                blank_skill_row,
                {
                    "id": "TestSkill1",
                    "target_rule": "SkillTargetRuleSelf",
                    "target_count": "0",
                    "cost": "1",
                    "description": "",
                },
            ],
            "스킬_에너미": [blank_skill_row, blank_skill_row],
        }
    )
    spreadsheet = _FakeSpreadsheet(sheets)

    (_buff_dict, skill_dict, *_rest) = load_battle_data(spreadsheet)

    assert "" not in skill_dict
    assert "TestSkill1" in skill_dict


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


def test_find_unreachable_enemy_buffs_detects_missing_timing():
    """apply_timing과 buff_add_timing이 둘 다 비어 있는 에너미 스킬의 버프
    부여 효과는, PRE에서도 POST에서도 CommandPartCalculator._process_buff_add()의
    add_timing 일치 조건을 통과하지 못해 버프가 조용히 드롭된다 — 이 조합을
    감지해야 한다."""
    sheets = _base_sheets(
        **{
            "스킬_에너미": [
                {
                    "id": "고장난 스킬",
                    "target_rule": "SkillTargetRuleColumn",
                    "target_count": 1,
                    "cost": 1,
                    "effect_0": "SkillEffectAddBuff",
                    "value_type_0": "버프",
                    "buff_name_0": "디버프_1",
                    "description": "",
                },
                {
                    "id": "정상 스킬",
                    "target_rule": "SkillTargetRuleColumn",
                    "target_count": 1,
                    "cost": 1,
                    "effect_0": "SkillEffectAddBuff",
                    "value_type_0": "버프",
                    "buff_name_0": "디버프_2",
                    "buff_add_timing_0": "적 행동 선언",
                    "description": "",
                },
            ]
        }
    )
    spreadsheet = _FakeSpreadsheet(sheets)

    (_buff_dict, skill_dict, *_rest) = load_battle_data(spreadsheet)
    broken = find_unreachable_enemy_buffs(
        {
            skill_id: data
            for skill_id, data in skill_dict.items()
            if skill_id in ("고장난 스킬", "정상 스킬")
        }
    )

    assert broken == [("고장난 스킬", "디버프_1")]


def test_find_unreachable_enemy_buffs_ignores_explicit_apply_timing():
    """effect_apply_timing_N이 명시돼 있으면(에너미 스킬 전체 처리 분기라
    add_timing을 검사하지 않음) buff_add_timing이 비어 있어도 정상이다."""
    sheets = _base_sheets(
        **{
            "스킬_에너미": [
                {
                    "id": "즉시 처리 스킬",
                    "target_rule": "SkillTargetRuleColumn",
                    "target_count": 1,
                    "cost": 1,
                    "effect_0": "SkillEffectAddBuff",
                    "value_type_0": "버프",
                    "buff_name_0": "디버프_3",
                    "effect_apply_timing_0": "적 행동 선언",
                    "description": "",
                }
            ]
        }
    )
    spreadsheet = _FakeSpreadsheet(sheets)

    (_buff_dict, skill_dict, *_rest) = load_battle_data(spreadsheet)
    broken = find_unreachable_enemy_buffs(skill_dict)

    assert broken == []
