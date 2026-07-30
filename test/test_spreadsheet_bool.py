from utils.spreadsheet_bool import format_spreadsheet_bool, parse_spreadsheet_bool


def test_parse_actual_bool_passthrough():
    assert parse_spreadsheet_bool(True) is True
    assert parse_spreadsheet_bool(False) is False


def test_parse_true_text_case_and_whitespace_insensitive():
    assert parse_spreadsheet_bool("TRUE") is True
    assert parse_spreadsheet_bool("true") is True
    assert parse_spreadsheet_bool(" True ") is True


def test_parse_false_text_is_false():
    """bool("FALSE")는 True가 되지만, 이 함수는 텍스트 내용을 실제로 해석해야 한다."""
    assert parse_spreadsheet_bool("FALSE") is False
    assert parse_spreadsheet_bool("false") is False


def test_parse_empty_or_other_text_is_false():
    assert parse_spreadsheet_bool("") is False
    assert parse_spreadsheet_bool("아무말") is False


def test_parse_none_is_false():
    assert parse_spreadsheet_bool(None) is False


def test_format_round_trips_through_parse():
    assert parse_spreadsheet_bool(format_spreadsheet_bool(True)) is True
    assert parse_spreadsheet_bool(format_spreadsheet_bool(False)) is False
