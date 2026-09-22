"""결투([결투]) 전용 규칙 테스트.

결투는 대련과 진행이 같고 세 가지만 다르다:
  1. 임시 체력이 최대 체력의 절반이 아니라 최대 체력 그대로다.
  2. 라운드 상한이 없다 — 한쪽이 전멸할 때까지 계속된다.
  3. 패배한 팀은 임시 체력이 아니라 시트의 실제 체력을 최대 체력의 50% 잃는다.
그리고 그 대가 구조 덕에 키워드 보정만은 허용된다(실제 체력에서 빠진다).

대련/상시전투와 공유하는 진행 규칙 자체는 test_practice_* 다른 파일에서
다루므로 여기서는 위 차이점만 확인한다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import pytest  # noqa: E402
from battle.core.command_processors import process_ally_command  # noqa: E402
from battle.core.commands.parser import parse_character_command  # noqa: E402
from battle.exceptions import CommandValidationError  # noqa: E402
from battle.objects.define import (  # noqa: E402
    FATE_INTERVENTION_HP_COST,
    BattlefieldColumnIndex,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.skill.effects import SkillEffectDamage  # noqa: E402
from battle.objects.skill.models import SkillData  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import (  # noqa: E402
    DUEL_DEFEAT_HP_PENALTY_PERCENT,
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

    def __init__(
        self,
        hp_by_name: dict[str, int],
        max_hp: int = 100,
        *,
        include_max_hp: bool = True,
    ):
        header = ["name", "curr_hp"] + (["max_hp"] if include_max_hp else [])
        rows: list[list] = [header]
        for name, hp in hp_by_name.items():
            rows.append([name, hp] + ([max_hp] if include_max_hp else []))
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


def test_duel_tracks_sheet_hp_separately_from_battle_hp():
    """임시 체력과 별개로 시트의 실제 체력을 들고 있어야 대가를 뺄 수 있다."""
    ctx = PracticeBattlefieldContext(
        buff_dict={}, skill_dict={}, mode=PracticeBattleMode.DUEL
    )
    ctx.add_character(
        get_test_preset(_A.name, max_hp=100, initial_hp=40),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )

    assert ctx.characters[_A].status.curr_hp == 100
    assert ctx.persistent_hp[_A].curr_hp == 40


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


# ── 3. 패배 대가 ─────────────────────────────────────────────────────────────


def test_defeated_side_loses_real_hp(monkeypatch):
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 80})
    ctx.characters[_B].status.curr_hp = 0

    post = main_module._finish_practice_battle(state, ps, "후공 행동")

    assert state.spreadsheet.hp_of(_B.name) == 30
    assert state.spreadsheet.hp_of(_A.name) == 100
    assert "**【결투 패배 처리】**" in post
    assert f"▹ {_B.name} | -50 → 30/100※" in post
    assert "※ 실제 체력" in post


def test_defeat_penalty_scales_with_each_max_hp(monkeypatch):
    """대가는 고정값이 아니라 캐릭터별 최대 체력의 절반이다. 최대 체력이
    홀수면 다른 절반 계산(max_hp // 2)과 같이 내림한다."""
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 101, _B.name: 101}, max_hp=101)
    ctx.characters[_B].status.curr_hp = 0

    main_module._finish_practice_battle(state, ps, "후공 행동")

    assert state.spreadsheet.hp_of(_B.name) == 101 - 101 // 2
    assert state.spreadsheet.hp_of(_A.name) == 101


def test_defeat_penalty_footnote_is_the_last_line_of_its_block(monkeypatch):
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 80})
    ctx.characters[_B].status.curr_hp = 0

    post = main_module._finish_practice_battle(state, ps, "후공 행동")

    block = post.split("**【결투 패배 처리】**")[1].split("\n\n")[0]
    assert block.strip().splitlines()[-1] == "※ 실제 체력"


def test_draw_applies_no_defeat_penalty(monkeypatch):
    """양 팀이 동시에 전멸하면(승자 없음) 어느 쪽도 실제 체력을 잃지 않는다."""
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 100})
    ctx.characters[_A].status.curr_hp = 0
    ctx.characters[_B].status.curr_hp = 0

    post = main_module._finish_practice_battle(state, ps, "후공 행동")

    assert state.spreadsheet.hp_of(_A.name) == 100
    assert state.spreadsheet.hp_of(_B.name) == 100
    assert "결투 패배 처리" not in post


def test_defeat_penalty_floors_at_zero_and_calls_world(monkeypatch):
    """실제 체력이 대가보다 적으면 0에서 멈추고, 사망 처리 확인을 요청한다."""
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 15})
    ctx.characters[_B].status.curr_hp = 0

    post = main_module._finish_practice_battle(state, ps, "후공 행동")

    assert state.spreadsheet.hp_of(_B.name) == 0
    assert f"▹ {_B.name} | -15 → 0/100※" in post
    assert (
        f"◊ {_B.name}의 체력이 0이 되어 사망 처리됩니다."
        f" @{main_module.WORLD_MASTODON_ID}" in post
    )


def test_retired_participant_still_pays_the_defeat_penalty(monkeypatch):
    """자진 기권해 필드에서 빠져도 패배 측이면 대가를 치른다."""
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 80})
    ctx.remove_character(_B)

    main_module._finish_practice_battle(state, ps, "후공 행동")

    penalty = 100 * DUEL_DEFEAT_HP_PENALTY_PERCENT // 100
    assert state.spreadsheet.hp_of(_B.name) == 80 - penalty


def test_defeat_penalty_reports_failure_when_max_hp_is_unreadable(monkeypatch):
    """최대 체력을 읽을 수 없으면 대가를 정할 수 없다. 0을 적용해 조용히
    넘기지 않고 admin에게 확인을 요청한다."""
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 80})
    state.spreadsheet = _FakeSpreadsheet(
        {_A.name: 100, _B.name: 80}, include_max_hp=False
    )
    ctx.characters[_B].status.curr_hp = 0

    post = main_module._finish_practice_battle(state, ps, "후공 행동")

    assert state.spreadsheet.hp_of(_B.name) == 80
    assert "실제 체력 반영에 실패했습니다" in post
    assert _B.name in post.split("실제 체력 반영에 실패했습니다")[1]


def test_practice_mode_never_touches_real_hp(monkeypatch):
    """대련은 패배해도 시트의 체력이 그대로여야 한다."""
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(hp_by_name={_A.name: 100, _B.name: 80})
    ps.mode = PracticeBattleMode.PRACTICE
    ctx.characters[_B].status.curr_hp = 0

    post = main_module._finish_practice_battle(state, ps, "후공 행동")

    assert state.spreadsheet.hp_of(_B.name) == 80
    assert "결투 패배 처리" not in post


# ── 4. 키워드 보정 ───────────────────────────────────────────────────────────


def _damage_skill() -> dict[str, SkillData]:
    return {
        "Cost2Skill": SkillData(
            id="Cost2Skill",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=2,
            effects=[
                SkillEffectDamage(
                    ValueSourceType.FIXED, 30, ValueType.INTEGER, None, None
                )
            ],
            description="",
        )
    }


def _run(ctx, text: str):
    command = parse_character_command(_A, text, ctx)
    assert command is not None
    return process_ally_command(ctx, command)


def test_duel_fate_boost_spends_sheet_hp_not_battle_hp(monkeypatch):
    _silence_field_sheet(monkeypatch)
    ctx, _ps, _state = _duel_state(
        hp_by_name={_A.name: 90, _B.name: 100},
        skill_dict=_damage_skill(),
        revival_count=1,
    )
    battle_hp_before = ctx.characters[_A].status.curr_hp

    _run(ctx, f"[공격+/{_B.name}]")

    assert ctx.characters[_A].status.curr_hp == battle_hp_before
    assert ctx.persistent_hp[_A].curr_hp == 90 - FATE_INTERVENTION_HP_COST


def test_duel_fate_boost_rejected_when_sheet_hp_is_too_low(monkeypatch):
    """임시 체력이 가득해도 실제 체력이 대가 이하면 쓸 수 없다."""
    _silence_field_sheet(monkeypatch)
    ctx, _ps, _state = _duel_state(
        hp_by_name={_A.name: FATE_INTERVENTION_HP_COST, _B.name: 100},
        skill_dict=_damage_skill(),
        revival_count=1,
    )

    with pytest.raises(CommandValidationError, match="체력"):
        _run(ctx, f"[공격+/{_B.name}]")

    assert ctx.persistent_hp[_A].curr_hp == FATE_INTERVENTION_HP_COST


def test_duel_fate_boost_cost_is_written_back_to_the_sheet(monkeypatch):
    _silence_field_sheet(monkeypatch)
    ctx, ps, state = _duel_state(
        hp_by_name={_A.name: 90, _B.name: 100},
        skill_dict=_damage_skill(),
        revival_count=1,
    )
    monkeypatch.setattr(main_module, "mark_fate_used_if_needed", lambda *a, **k: None)

    command = parse_character_command(_A, f"[공격+/{_B.name}]", ctx)
    assert command is not None
    process_ally_command(ctx, command)
    warning = main_module._apply_duel_fate_cost(state, ps, _A, command)

    assert warning == ""
    assert state.spreadsheet.hp_of(_A.name) == 90 - FATE_INTERVENTION_HP_COST


def test_practice_mode_still_rejects_fate_boost():
    ctx = PracticeBattlefieldContext(
        buff_dict={}, skill_dict={}, mode=PracticeBattleMode.PRACTICE
    )
    assert ctx.allow_fate_intervention is False


def test_duel_still_rejects_items():
    ctx = PracticeBattlefieldContext(
        buff_dict={}, skill_dict={}, mode=PracticeBattleMode.DUEL
    )
    assert ctx.allow_item_usage is False
    assert ctx.allow_fate_intervention is True
