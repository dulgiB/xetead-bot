import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import gspread  # noqa: E402
import pytest  # noqa: E402

from battle.core.battlefield_context import BattlefieldContext  # noqa: E402
from battle.objects.define import BattlefieldColumnIndex, FactionType  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from bot import bio_hp_sync, load_data, log_sheets  # noqa: E402
from helpers import apply_values_batch_update, get_test_preset  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, result: str = "updated"):
        self.lookup_headers: list[dict | None] = []
        self.put_headers: list[dict | None] = []
        self.result = result
        self.lookups: list[str] = []
        self.puts: list[tuple[str, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.lookup_headers.append(headers)
        self.lookups.append(params["acct"])
        return _FakeResponse({"id": f"id-{params['acct']}"})

    def put(self, url, data=None, headers=None, timeout=None):
        self.put_headers.append(headers)
        self.puts.append((url, data))
        return _FakeResponse({"result": self.result})


@pytest.fixture
def notified(monkeypatch):
    calls: list[tuple[str, int, int | None]] = []
    monkeypatch.setattr(
        bio_hp_sync,
        "notify",
        lambda acct, curr, max_hp: calls.append((acct, curr, max_hp)),
    )
    return calls


def test_sync_looks_up_account_once_and_sends_both_values():
    session = _FakeSession()
    syncer = bio_hp_sync.BioHpSyncer("https://example.test/", "token", session=session)

    assert syncer.sync("player", 70, 100) == "updated"
    syncer.sync("player", 60, 100)

    # 토큰 범위가 관리자 쓰기뿐이라 공개 API인 계정 조회에는 붙이지 않는다.
    assert session.lookup_headers == [None]
    assert session.put_headers == [{"Authorization": "Bearer token"}] * 2
    assert session.lookups == ["player"]
    assert session.puts == [
        (
            "https://example.test/api/v1/admin/accounts/id-player/bio_hp",
            {"current_hp": 70, "max_hp": 100},
        ),
        (
            "https://example.test/api/v1/admin/accounts/id-player/bio_hp",
            {"current_hp": 60, "max_hp": 100},
        ),
    ]


def test_pending_updates_for_the_same_account_keep_only_the_latest():
    """광역기로 여러 번 맞아도 최종 체력 하나만 보내면 된다."""
    session = _FakeSession()
    syncer = bio_hp_sync.BioHpSyncer("https://example.test", "token", session=session)
    syncer.notify("player", 80, 100)
    syncer.notify("player", 50, 100)
    syncer.notify("other", 30, 40)

    syncer.start()
    assert syncer.wait_idle(timeout=5)

    assert sorted(data["current_hp"] for _, data in session.puts) == [30, 50]


def test_notify_does_nothing_without_installed_syncer():
    bio_hp_sync.notify("player", 10, 100)  # 예외 없이 넘어가야 한다.


class _FakeHpWorksheet:
    def __init__(self, rows: list[list], title: str):
        self.title = title
        self._rows = rows

    def get_values(self, value_render_option=None, pad_values=True):
        return self._rows

    def update_cell(self, row, col, value):
        self._rows[row - 1][col - 1] = value


class _FakeSpreadsheet:
    def __init__(self, rows: list[list], fail: bool = False):
        self._sheets = {"캐릭터": _FakeHpWorksheet(rows, "캐릭터")}
        self._fail = fail

    def worksheet(self, name):
        if name not in self._sheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._sheets[name]

    def values_batch_update(self, body):
        if self._fail:
            raise RuntimeError("시트 API 실패")
        apply_values_batch_update(self._sheets, body)


def _context() -> BattlefieldContext:
    ctx = BattlefieldContext(buff_dict={}, skill_dict={})
    for idx, name in enumerate(("아군1", "아군2")):
        ctx.add_character(
            get_test_preset(name), FactionType.ALLY, BattlefieldColumnIndex(idx)
        )
    return ctx


def _rows() -> list[list]:
    return [
        ["name", "mastodon_id", "curr_hp", "max_hp"],
        ["아군1", "player1", "100", "100"],
        ["아군2", "", "100", "100"],
    ]


def test_hp_write_back_notifies_bio_sync_for_accounts(notified):
    ctx = _context()
    ctx.characters[CharacterId("아군1")].status.curr_hp = 70
    ctx.characters[CharacterId("아군2")].status.curr_hp = 60

    log_sheets.write_back_character_hp(
        _FakeSpreadsheet(_rows()), ctx, ["아군1", "아군2"]
    )

    # 계정이 없는 캐릭터는 notify()가 건너뛴다.
    assert sorted(notified) == [("", 60, 100), ("player1", 70, 100)]


def test_failed_hp_write_does_not_touch_bio(notified):
    ctx = _context()
    ctx.characters[CharacterId("아군1")].status.curr_hp = 70

    log_sheets.write_back_character_hp(
        _FakeSpreadsheet(_rows(), fail=True), ctx, ["아군1"]
    )

    assert notified == []


def test_sheet_hp_edited_by_gm_is_sent_to_bio(notified):
    ctx = _context()
    rows = _rows()
    rows[1][2] = "90"

    log_sheets.sync_hp_from_sheet(
        _FakeSpreadsheet(rows), ctx, {"아군1": 100, "아군2": 100}
    )

    assert notified == [("player1", 90, 100)]


def test_noncombat_hp_update_notifies_bio_sync(notified):
    load_data.update_character_curr_hp(_FakeSpreadsheet(_rows()), "아군1", 45)

    assert notified == [("player1", 45, 100)]
