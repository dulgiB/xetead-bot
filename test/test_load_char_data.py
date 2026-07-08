import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

from bot import main as main_module  # noqa: E402
from bot.load_data import load_char_data  # noqa: E402


def _row(**overrides) -> dict:
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


class _FakeWorksheet:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def get_all_records(self, value_render_option=None):
        return self._rows


class _FakeSpreadsheet:
    def __init__(self, rows: list[dict]):
        self._ws = _FakeWorksheet(rows)

    def worksheet(self, name):
        assert name == "캐릭터"
        return self._ws


def test_load_char_data_skips_row_with_invalid_enum_value():
    """수정 중이라 m_res 등이 비어/깨져 있는 행은 건너뛰고 나머지는 정상 로드되어야 한다."""
    rows = [
        _row(name="정상", mastodon_id="ok@example.com"),
        _row(name="작성중", mastodon_id="editing@example.com", m_res=""),
    ]
    spreadsheet = _FakeSpreadsheet(rows)

    char_dict, name_dict, noncombat_char_dict = load_char_data(spreadsheet)

    assert "ok@example.com" in char_dict
    assert "정상" in name_dict
    assert "editing@example.com" not in char_dict
    assert "작성중" not in name_dict


def test_load_char_data_skips_completely_blank_row():
    """이름과 mastodon_id가 모두 비어 있는 빈 행은 조용히 무시되어야 한다."""
    rows = [_row(), _row(name="", mastodon_id="")]
    spreadsheet = _FakeSpreadsheet(rows)

    char_dict, name_dict, noncombat_char_dict = load_char_data(spreadsheet)

    assert len(char_dict) == 1
    assert len(name_dict) == 1


def test_reload_char_data_replaces_state_dicts(monkeypatch):
    """reload_char_data는 매번 load_char_data를 호출해 state의 캐릭터 캐시를 갱신한다."""
    from bot.main import BotState

    state = BotState(char_dict={}, name_dict={}, noncombat_char_dict={}, spreadsheet=object())
    fresh = ({"acct": "new"}, {"새캐릭터": "new"}, {"acct": "new_noncombat"})
    monkeypatch.setattr(main_module, "load_char_data", lambda spreadsheet: fresh)

    main_module.reload_char_data(state)

    assert state.char_dict == fresh[0]
    assert state.name_dict == fresh[1]
    assert state.noncombat_char_dict == fresh[2]
