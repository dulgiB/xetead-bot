from spreadsheets.models.combat import CombatCharacterDataFromSpreadsheet


def _raw(**overrides) -> dict:
    base = {
        "name": "테스트",
        "mastodon_id": "test@example.com",
        "curr_hp": 100,
        "max_hp": 100,
        "atk": 5,
        "attack_range": 3,
        "m_res": "보통",
        "is_magic": False,
        "max_cost": 3,
    }
    base.update(overrides)
    return base


def test_curr_hp_zero_is_preserved_not_defaulted_to_full():
    """curr_hp가 명시적으로 0이면 만피가 아니라 0으로 파싱되어야 한다."""
    data = CombatCharacterDataFromSpreadsheet.from_dict(_raw(curr_hp=0))
    assert data.curr_hp == 0


def test_curr_hp_blank_cell_is_none():
    """curr_hp 셀이 비어 있으면(빈 문자열) None으로 파싱되어 만피로 취급된다."""
    data = CombatCharacterDataFromSpreadsheet.from_dict(_raw(curr_hp=""))
    assert data.curr_hp is None


def test_curr_hp_positive_value_is_parsed_as_int():
    data = CombatCharacterDataFromSpreadsheet.from_dict(_raw(curr_hp=42))
    assert data.curr_hp == 42
