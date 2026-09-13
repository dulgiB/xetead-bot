"""결투([결투]) 전용 규칙 테스트.

결투는 대련과 진행이 같고 두 가지가 다르다:
  1. 임시 체력이 최대 체력의 절반이 아니라 최대 체력 그대로다.
  2. 라운드 상한이 없다 — 한쪽이 전멸할 때까지 계속된다.

대련/상시전투와 공유하는 진행 규칙 자체는 test_practice_* 다른 파일에서
다루므로 여기서는 위 차이점만 확인한다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.core.commands.parser import parse_character_command  # noqa: E402
from battle.objects.define import BattlefieldColumnIndex  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import (  # noqa: E402
    PracticeBattleMode,
    PracticeRoundPhase,
    SideType,
)
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot import main as main_module  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402
from helpers import get_test_preset  # noqa: E402

_A = CharacterId("Catastrophe")
_B = CharacterId("Adversary")


class _FakeWorksheet:
    def __init__(self, title: str, rows: list[list]):
        self.title = title
        self.rows = rows
        self.written: list[tuple[int, int, object]] = []

    def get_values(self, **kwargs):
        return self.rows

    def update_cell(self, row: int, col: int, value) -> None:
        self.written.append((row, col, value))
        self.rows[row - 1][col - 1] = value


class _FakeSpreadsheet:
    """ "캐릭터" 시트만 가진 최소 스프레드시트."""

    def __init__(self, hp_by_name: dict[str, int], max_hp: int = 100):
        rows: list[list] = [["name", "curr_hp", "max_hp"]]
        for name, hp in hp_by_name.items():
            rows.append([name, hp, max_hp])
        self._sheets = {"캐릭터": _FakeWorksheet("캐릭터", rows)}

    def worksheet(self, name: str) -> _FakeWorksheet:
        import gspread

        if name not in self._sheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return self._sheets[name]

    def hp_of(self, name: str) -> int:
        for row in self._sheets["캐릭터"].rows[1:]:
            if row[0] == name:
                return row[1]
        raise KeyError(name)


def _duel_state(
    *,
    hp_by_name: dict[str, int],
    max_hp: int = 100,
    skill_dict: dict | None = None,
    fate_date: str = "",
    revival_count: int = 0,
) -> tuple[PracticeBattlefieldContext, PracticeBattleState, BotState]:
    """배치까지 끝난 1:1 결투(A=1팀, B=2팀)를 만든다."""
    ctx = PracticeBattlefieldContext(
        buff_dict={}, skill_dict=skill_dict or {}, mode=PracticeBattleMode.DUEL
    )
    char_dict = {
        "acct_a": get_test_preset(
            _A.name,
            max_hp=max_hp,
            initial_hp=hp_by_name[_A.name],
            revival_count=revival_count,
            fate_date=fate_date,
            skill_1_id="Cost2Skill" if skill_dict else None,
        ),
        "acct_b": get_test_preset(
            _B.name, max_hp=max_hp, initial_hp=hp_by_name[_B.name]
        ),
    }
    ps = PracticeBattleState(
        context=ctx,
        manager=PracticeRoundManager(ctx),
        mode=PracticeBattleMode.DUEL,
        active_post_id=1,
        declared={
            "acct_a": (SideType.SIDE_1, BattlefieldColumnIndex(3)),
            "acct_b": (SideType.SIDE_2, BattlefieldColumnIndex(3)),
        },
    )
    state = BotState(
        char_dict=char_dict,
        name_dict={data.name: data for data in char_dict.values()},
        noncombat_char_dict={},
        spreadsheet=_FakeSpreadsheet(hp_by_name, max_hp=max_hp),
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    main_module._start_practice_battle(state, ps)
    return ctx, ps, state


def _silence_field_sheet(monkeypatch) -> None:
    """ "필드" 시트 기록은 이 테스트의 관심사가 아니다."""
    monkeypatch.setattr(main_module, "_upsert_practice_field_row", lambda *a, **k: None)


# ── 1. 임시 체력 ─────────────────────────────────────────────────────────────


def test_duel_places_characters_with_full_max_hp():
    ctx = PracticeBattlefieldContext(
        buff_dict={}, skill_dict={}, mode=PracticeBattleMode.DUEL
    )
    ctx.add_character(
        get_test_preset(_A.name, max_hp=100), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )

    assert ctx.characters[_A].status.curr_hp == 100


def test_practice_still_halves_max_hp():
    ctx = PracticeBattlefieldContext(
        buff_dict={}, skill_dict={}, mode=PracticeBattleMode.PRACTICE
    )
    ctx.add_character(
        get_test_preset(_A.name, max_hp=100), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )

    assert ctx.characters[_A].status.curr_hp == 50


# ── 2. 라운드 상한 ───────────────────────────────────────────────────────────


def test_duel_starts_without_round_limit(monkeypatch):
    _silence_field_sheet(monkeypatch)
    _ctx, ps, _state = _duel_state(hp_by_name={_A.name: 100, _B.name: 100})

    assert ps.round_limit is None


def test_duel_continues_past_the_practice_round_limit(monkeypatch):
    """대련이었다면 끝났을 라운드 수를 넘겨도 양쪽이 살아 있으면 계속된다.

    같은 인원(2명)의 대련이라면 상한은 3라운드다."""
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 100}, max_hp=1000)

    for _ in range(5):
        for _phase in (
            PracticeRoundPhase.FIRST_MOVER_ACTION,
            PracticeRoundPhase.SECOND_MOVER_ACTION,
        ):
            current_phase = ps.phase
            assert current_phase is not None
            _declare_everyone_in_phase(ctx, ps)
            _post, ended = main_module._finalize_practice_phase(
                state, ps, current_phase
            )
            assert ended is False

    assert ps.round_n > 3
    assert ps.round_limit is None


def _declare_everyone_in_phase(ctx, ps) -> None:
    """이번 페이즈에 행동할 캐릭터 전원이 상대를 한 번씩 공격하게 한다."""
    for char_id in list(ps.pending_actors()):
        foe = _B if char_id == _A else _A
        command = parse_character_command(char_id, f"[공격/{foe.name}]", ctx)
        assert command is not None
        ps.manager.process_command(command)


def test_duel_ends_when_one_side_is_wiped(monkeypatch):
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 100})
    ctx.characters[_B].status.curr_hp = 0

    ps.manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
    post, ended = main_module._finalize_practice_phase(
        state, ps, PracticeRoundPhase.SECOND_MOVER_ACTION
    )

    assert ended is True
    assert post is not None and "결투 종료" in post
