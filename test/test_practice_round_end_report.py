"""대련/결투의 라운드 종료·전투 종료 정산을 "언제 돌리고 어떻게 보여주는지"
확인한다.

두 가지 규칙이 얽혀 있다:

1. 라운드가 정상적으로 닫히면 그 라운드 종료 처리(DoT/HoT, 자동 탈락)를
   다음 라운드 공지에 실어야 한다. 실지 않으면 플레이어는 라운드가 넘어갈
   때 체력이 줄어든 것만 보고 이유를 알 수 없다.
2. 한쪽이 쓰러져 승부가 난 라운드는 아예 닫지 않는다 — 닫으면 이긴 쪽이
   자기에게 걸린 DoT나 [재앙] 대가로 함께 쓰러져 무승부가 되고, 그러면
   진 쪽마저 패배 대가를 치르지 않는다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.objects.buff.buff_base import BuffAddData  # noqa: E402
from battle.objects.buff.models import BuffData  # noqa: E402
from battle.objects.define import (  # noqa: E402
    BattlefieldColumnIndex,
    BuffType,
    ValueType,
)
from battle.objects.models import CharacterId  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import PracticeBattleMode, SideType  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot.main import BotState, _handle_practice_command  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402
from helpers import get_test_preset  # noqa: E402

_ACCT_BY_SIDE = {SideType.SIDE_1: "acct_a", SideType.SIDE_2: "acct_b"}


def _dot_buff(value: int) -> BuffData:
    """라운드 종료마다 고정 대미지를 주는, 지속시간 없는 디버프."""
    return BuffData(
        id="맹독",
        buff_class_name="BuffDamageOverTime",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=value,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.DEBUFF,
        description="",
    )


def _catastrophe_buff() -> BuffData:
    return BuffData(
        id="재앙",
        buff_class_name="BuffCatastrophe",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=5,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.NEUTRAL,
        description="",
        max_stack=10,
    )


def _setup(
    buff_dict: dict[str, BuffData],
    *,
    a_max_hp: int = 100,
    b_max_hp: int = 100,
    round_limit: int = 5,
    mode: PracticeBattleMode = PracticeBattleMode.PRACTICE,
) -> tuple[PracticeBattlefieldContext, PracticeBattleState, BotState]:
    ctx = PracticeBattlefieldContext(buff_dict=buff_dict, skill_dict={}, mode=mode)
    ctx.add_character(
        get_test_preset("Catastrophe", max_hp=a_max_hp),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(
        get_test_preset("Adversary", max_hp=b_max_hp),
        SideType.SIDE_2,
        BattlefieldColumnIndex(0),
    )
    manager = PracticeRoundManager(ctx)
    ps = PracticeBattleState(
        context=ctx, manager=manager, mode=mode, round_limit=round_limit
    )
    ps.snapshot_initial_max_hp()
    ps.snapshot_roster()
    ps.start_round()
    state = BotState(
        char_dict={
            "acct_a": get_test_preset("Catastrophe", max_hp=a_max_hp),
            "acct_b": get_test_preset("Adversary", max_hp=b_max_hp),
        },
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    ps.active_post_id = 5000
    state.practices[5000] = ps
    return ctx, ps, state


def _play_phase(state: BotState, ps: PracticeBattleState, command: str) -> str | None:
    """지금 차례인 팀의 캐릭터가 command를 선언한다. 페이즈가 넘어가며
    만들어진 공지 텍스트를 반환한다(아직 안 넘어갔으면 None)."""
    acct = _ACCT_BY_SIDE[ps.context.get_side(ps.pending_actors()[0])]
    _reply, _calc, game_post, _log, _ended = _handle_practice_command(
        acct, command, state, ps
    )
    return game_post


def test_round_end_processing_is_shown_in_the_next_round_post():
    """정상적으로 닫힌 라운드의 종료 처리는 다음 라운드 공지에 실린다."""
    ctx, ps, state = _setup({"맹독": _dot_buff(7)})
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("Catastrophe"),
            applied_to=CharacterId("Adversary"),
            buff_id="맹독",
        )
    )

    assert _play_phase(state, ps, "[이동/2]") is not None  # 선공 → 후공
    game_post = _play_phase(state, ps, "[이동/2]")  # 후공 → 라운드 종료

    assert game_post is not None
    assert "라운드 종료 처리" in game_post
    assert "Adversary" in game_post
    assert ctx.characters[CharacterId("Adversary")].status.curr_hp == 50 - 7


def test_round_is_not_closed_when_a_side_is_knocked_out_in_the_first_phase():
    """선공 페이즈에서 승부가 나면 라운드 종료 처리도 전투 종료 처리도 돌지
    않는다 — 돌리면 이긴 쪽이 자기 DoT/[재앙] 대가에 함께 쓰러진다."""
    ctx, ps, state = _setup(
        {"맹독": _dot_buff(999), "재앙": _catastrophe_buff()}, b_max_hp=2
    )
    winner_id = CharacterId("Catastrophe")
    # 이긴 쪽이 자기 차례에 상대를 눕히지만, 스스로도 라운드 종료 DoT와
    # 전투 종료 [재앙] 대가를 잔뜩 안고 있는 상황.
    ctx.buff_container.add(
        BuffAddData(given_by=winner_id, applied_to=winner_id, buff_id="맹독")
    )
    ctx.buff_container.add(
        BuffAddData(
            given_by=winner_id, applied_to=winner_id, buff_id="재앙", stack_value=10
        )
    )
    hp_before = ctx.characters[winner_id].status.curr_hp

    # 선공이 2팀이면 아무 일도 없는 이동만 시켜 1팀 차례로 넘긴다.
    if ps.context.get_side(ps.pending_actors()[0]) == SideType.SIDE_2:
        _play_phase(state, ps, "[이동/2]")

    game_post = _play_phase(state, ps, "[공격/Adversary]")

    assert game_post is not None
    assert "종료" in game_post
    assert "승자: 1팀" in game_post
    assert "라운드 종료 처리" not in game_post
    assert "전투 종료 처리" not in game_post
    assert ctx.characters[winner_id].status.curr_hp == hp_before
    assert not state.practices


def test_draw_is_labelled_as_draw():
    """무승부는 "승자: 알 수 없음"이 아니라 무승부로 적는다."""
    _ctx, ps, state = _setup({}, round_limit=1)

    assert _play_phase(state, ps, "[이동/2]") is not None
    game_post = _play_phase(state, ps, "[이동/2]")

    assert game_post is not None
    assert "결과: 무승부" in game_post
    assert "알 수 없음" not in game_post


def test_battle_end_processing_runs_when_both_sides_survive():
    """라운드 상한으로 양쪽이 살아서 끝나면 전투 종료 처리는 그대로 돈다 —
    KO 종료에서만 건너뛴다는 것을 확인한다."""
    ctx, ps, state = _setup({"재앙": _catastrophe_buff()}, round_limit=1)
    holder = CharacterId("Adversary")
    ctx.buff_container.add(
        BuffAddData(given_by=holder, applied_to=holder, buff_id="재앙", stack_value=3)
    )

    assert _play_phase(state, ps, "[이동/2]") is not None
    game_post = _play_phase(state, ps, "[이동/2]")

    assert game_post is not None
    assert "전투 종료 처리" in game_post
    assert ctx.characters[holder].status.curr_hp == 50 - 3 * 5
