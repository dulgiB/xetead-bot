import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import gspread  # noqa: E402

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
    """'캐릭터' 시트는 항상 존재하고, '에너미' 시트는 전달된 경우에만 존재한다
    (실제 스프레드시트에 에너미 시트가 아직 없는 경우를 재현)."""

    def __init__(self, rows: list[dict], enemy_rows: list[dict] | None = None):
        self._sheets = {"캐릭터": _FakeWorksheet(rows)}
        if enemy_rows is not None:
            self._sheets["에너미"] = _FakeWorksheet(enemy_rows)

    def worksheet(self, name):
        assert name in ("캐릭터", "에너미")
        if name not in self._sheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._sheets[name]


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


def test_load_char_data_without_enemy_sheet_still_loads_characters():
    """'에너미' 시트가 아직 없어도 '캐릭터' 시트 로드는 정상 동작해야 한다."""
    rows = [_row()]
    spreadsheet = _FakeSpreadsheet(rows)

    char_dict, name_dict, noncombat_char_dict = load_char_data(spreadsheet)

    assert "test@example.com" in char_dict
    assert "테스트" in name_dict


def test_load_char_data_merges_enemy_sheet_by_name_and_mastodon_id():
    """'에너미' 시트 행은 name_dict에 항상 반영되고, mastodon_id가 있는 경우에만
    char_dict에도 등록되며, noncombat_char_dict에는 등록되지 않아야 한다
    (에너미 시트에는 비전투 스테이터스/골드/일일 의뢰 컬럼이 없기 때문)."""
    rows = [_row()]
    enemy_rows = [
        _row(name="고블린", mastodon_id="", curr_hp=20, max_hp=20),
        _row(name="보스", mastodon_id="boss@example.com", curr_hp=200, max_hp=200),
    ]
    spreadsheet = _FakeSpreadsheet(rows, enemy_rows=enemy_rows)

    char_dict, name_dict, noncombat_char_dict = load_char_data(spreadsheet)

    assert "고블린" in name_dict
    assert "고블린" not in char_dict

    assert "boss@example.com" in char_dict
    assert "보스" in name_dict
    assert "boss@example.com" not in noncombat_char_dict


def test_load_char_data_skips_invalid_enemy_row():
    """에너미 시트에서 파싱에 실패하는 행은 건너뛰고 나머지는 정상 로드되어야 한다."""
    rows = [_row()]
    enemy_rows = [
        _row(name="정상 에너미", mastodon_id="", m_res="보통"),
        _row(name="작성중 에너미", mastodon_id="", m_res=""),
    ]
    spreadsheet = _FakeSpreadsheet(rows, enemy_rows=enemy_rows)

    char_dict, name_dict, noncombat_char_dict = load_char_data(spreadsheet)

    assert "정상 에너미" in name_dict
    assert "작성중 에너미" not in name_dict


def test_reload_char_data_replaces_state_dicts(monkeypatch):
    """reload_char_data는 매번 load_char_data를 호출해 state의 캐릭터 캐시를 갱신한다."""
    from bot.main import BotState

    state = BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=object(),
        field_spreadsheet=object(),
        log_spreadsheet=object(),
    )
    fresh = ({"acct": "new"}, {"새캐릭터": "new"}, {"acct": "new_noncombat"})
    monkeypatch.setattr(
        main_module, "load_char_data", lambda spreadsheet, cache=None: fresh
    )

    main_module.reload_char_data(state)

    assert state.char_dict == fresh[0]
    assert state.name_dict == fresh[1]
    assert state.noncombat_char_dict == fresh[2]
