from bot.load_data import load_general_quest_sheet


class _FakeWorksheet:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def get_all_records(self, value_render_option=None):
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, rows: list[dict]):
        self._ws = _FakeWorksheet(rows)

    def worksheet(self, name):
        assert name == "일반 의뢰"
        return self._ws


def _location_row(id_: str, active) -> dict:
    return {"id": id_, "name": "", "active": active, "description_quest": id_}


def _quest_row(id_: str, location: str, active) -> dict:
    return {
        "id": id_,
        "name": f"{location} 의뢰",
        "location": location,
        "active": active,
    }


def test_quests_are_selected_by_active_not_id():
    rows = [
        _location_row("장소_1", True),
        _location_row("장소_2", False),
        _quest_row("q1", "광장", True),
        _quest_row("장소_1_운반", "항구", False),
        _quest_row("q3", "상점가", "TRUE"),
        _quest_row("q4", "골목", ""),
    ]

    location, quests = load_general_quest_sheet(_FakeSpreadsheet(rows))

    assert location is not None and location.id == "장소_1"
    assert [q.location for q in quests] == ["광장", "상점가"]


def test_active_location_without_active_quests():
    rows = [_location_row("장소_1", True), _quest_row("q1", "광장", False)]

    location, quests = load_general_quest_sheet(_FakeSpreadsheet(rows))

    assert location is not None
    assert quests == []


def test_no_active_location_returns_nothing():
    rows = [_location_row("장소_1", False), _quest_row("q1", "광장", True)]

    assert load_general_quest_sheet(_FakeSpreadsheet(rows)) == (None, [])


def test_row_with_location_but_no_name_is_quest_row():
    """자율 탐사 전용 선택지는 name 없이 location만 채운다. 장소 행으로
    읽히면 활성 장소를 가로채거나 메뉴에서 빠진다."""
    rows = [
        {"id": "장소_1_특수", "name": "", "location": "골목", "active": True},
        _location_row("장소_1", True),
    ]

    location, quests = load_general_quest_sheet(_FakeSpreadsheet(rows))

    assert location is not None and location.id == "장소_1"
    assert [q.id for q in quests] == ["장소_1_특수"]
