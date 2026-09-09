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


def test_revival_count_defaults_to_zero():
    """컬럼이 없는 시트("에너미")도, 값이 비어 있는 셀도 0회로 읽는다."""
    assert CombatCharacterDataFromSpreadsheet.from_dict(_raw()).revival_count == 0
    assert (
        CombatCharacterDataFromSpreadsheet.from_dict(
            _raw(revival_count="")
        ).revival_count
        == 0
    )


def test_revival_count_value_is_parsed_as_int():
    data = CombatCharacterDataFromSpreadsheet.from_dict(_raw(revival_count=3))
    assert data.revival_count == 3


def test_fate_date_defaults_to_empty():
    """컬럼이 없거나 비어 있으면 "한 번도 안 씀"으로 읽는다."""
    assert CombatCharacterDataFromSpreadsheet.from_dict(_raw()).fate_date == ""
    assert (
        CombatCharacterDataFromSpreadsheet.from_dict(_raw(fate_date="")).fate_date == ""
    )


def test_has_used_fate_on_compares_date():
    """오늘 날짜와 같을 때만 "이미 씀"이다 — 날짜가 바뀌면 자동으로 풀린다."""
    data = CombatCharacterDataFromSpreadsheet.from_dict(_raw(fate_date="2026-09-09"))
    assert data.has_used_fate_on("2026-09-09") is True
    assert data.has_used_fate_on("2026-09-10") is False


def test_has_used_fate_on_is_false_when_never_used():
    """빈 값은 어떤 날짜와도 일치하지 않아야 한다(빈 문자열끼리 비교 주의)."""
    data = CombatCharacterDataFromSpreadsheet.from_dict(_raw())
    assert data.has_used_fate_on("") is False
    assert data.has_used_fate_on("2026-09-09") is False
