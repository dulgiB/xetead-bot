from bot.load_data import load_daily_quest_result_messages
from spreadsheets.models.quest import DailyQuestSuccessType


class _FakeWorksheet:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def get_all_records(self, value_render_option=None):
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, rows: list[dict]):
        self._ws = _FakeWorksheet(rows)

    def worksheet(self, name):
        assert name == "일일 의뢰 결과 메시지"
        return self._ws


def test_only_active_rows_are_loaded():
    rows = [
        {"success_type": "대성공", "message": "켜짐", "active": True},
        {"success_type": "대성공", "message": "꺼짐", "active": False},
        {"success_type": "성공", "message": "문자열 켜짐", "active": "TRUE"},
        {"success_type": "성공", "message": "빈 칸", "active": ""},
    ]

    messages = load_daily_quest_result_messages(_FakeSpreadsheet(rows))

    assert [(m.success_type, m.message) for m in messages] == [
        (DailyQuestSuccessType.GREAT_SUCCESS, "켜짐"),
        (DailyQuestSuccessType.SUCCESS, "문자열 켜짐"),
    ]
