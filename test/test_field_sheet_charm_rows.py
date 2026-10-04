"""공개 "필드" 시트의 부적 행: 부적 하나가 행 하나를 차지하고, 소지자 열 ±
부적 사거리를 병합해 이름을 적으며 효과는 메모에 넣는다."""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.objects.define import BattlefieldColumnIndex, FactionType  # noqa: E402
from bot.commands.admin import _check_charm_row_capacity  # noqa: E402
from bot.field_sheet_renderer import (  # noqa: E402
    CHARM_ROW_COUNT,
    _ALLY_MAIN_ROW_START,
    _CHARM_ROW_START,
    _build_charm_rows,
    _charm_merge_requests,
)
from test_bot_admin import _make_state  # noqa: E402
from test_charm_aura import (  # noqa: E402
    CHARM_ID,
    FAR,
    FOE,
    HOLDER,
    NEAR,
    _charm_item,
    _make_context,
    _place,
)

_ROW = _CHARM_ROW_START


def _cells(grid):
    return {
        (offset, col): text
        for offset, row in enumerate(grid)
        for col, text in enumerate(row)
        if text
    }


def test_charm_row_spans_holder_column_plus_minus_range():
    ctx = _make_context()
    _place(ctx, HOLDER, FactionType.ALLY, 3)

    grid, notes, merges = _build_charm_rows(ctx)

    # 4열 ± 1 → 3~5열 = 시트 D~F
    assert _cells(grid) == {(0, 2): f"{CHARM_ID}[{HOLDER.name}]"}
    assert merges == [(_ROW, 4, 6)]
    assert notes[f"D{_ROW}"] == f"[{CHARM_ID}] 부활 4회 상태처럼 취급한다."


def test_range_is_clipped_at_the_field_edge():
    ctx = _make_context()
    _place(ctx, HOLDER, FactionType.ALLY, 0)

    _, _, merges = _build_charm_rows(ctx)

    assert merges == [(_ROW, 2, 3)]


def test_row_follows_the_holder():
    ctx = _make_context()
    _place(ctx, HOLDER, FactionType.ALLY, 3)
    ctx.move_character_to(HOLDER, BattlefieldColumnIndex(6))

    grid, notes, merges = _build_charm_rows(ctx)

    assert merges == [(_ROW, 7, 8)]
    assert _cells(grid) == {(0, 5): f"{CHARM_ID}[{HOLDER.name}]"}
    # 이전 자리의 메모는 비워진다.
    assert notes[f"D{_ROW}"] == ""


def test_empty_when_no_charm_is_in_play():
    ctx = _make_context(owners=())
    _place(ctx, NEAR, FactionType.ALLY, 3)

    grid, notes, merges = _build_charm_rows(ctx)

    assert _cells(grid) == {}
    assert merges == []
    assert set(notes.values()) == {""}
    assert len(notes) == 7 * CHARM_ROW_COUNT


def test_enemy_holder_is_not_drawn():
    ctx = _make_context(owners=(FOE.name,))
    _place(ctx, FOE, FactionType.ENEMY, 3)

    _, _, merges = _build_charm_rows(ctx)

    assert merges == []


def test_charms_beyond_the_row_count_are_left_out():
    ctx = _make_context(owners=(HOLDER.name, FAR.name))
    _place(ctx, HOLDER, FactionType.ALLY, 3)
    _place(ctx, FAR, FactionType.ALLY, 5)

    grid, _, merges = _build_charm_rows(ctx)

    assert len(merges) == CHARM_ROW_COUNT
    assert _cells(grid) == {(0, 2): f"{CHARM_ID}[{HOLDER.name}]"}


def test_merge_requests_unmerge_the_row_first():
    requests = _charm_merge_requests(7, [(_ROW, 4, 6)])

    assert requests[0] == {
        "unmergeCells": {
            "range": {
                "sheetId": 7,
                "startRowIndex": _ROW - 1,
                "endRowIndex": _ALLY_MAIN_ROW_START - 1,
                "startColumnIndex": 1,
                "endColumnIndex": 8,
            }
        }
    }
    assert requests[1]["mergeCells"]["range"] == {
        "sheetId": 7,
        "startRowIndex": _ROW - 1,
        "endRowIndex": _ROW,
        "startColumnIndex": 3,
        "endColumnIndex": 6,
    }


def test_single_column_range_needs_no_merge():
    requests = _charm_merge_requests(7, [(_ROW, 4, 4)])

    assert [next(iter(r)) for r in requests] == ["unmergeCells"]


def _state_with(ctx):
    state = _make_state()
    assert state.session is not None
    state.session.context = ctx
    return state


def test_capacity_warning_when_more_charms_than_rows():
    ctx = _make_context(owners=(HOLDER.name, FAR.name))
    _place(ctx, HOLDER, FactionType.ALLY, 3)
    _place(ctx, FAR, FactionType.ALLY, 5)

    warning = _check_charm_row_capacity(_state_with(ctx))

    assert warning is not None
    assert f"{CHARM_ID}[{FAR.name}]" in warning


def test_no_capacity_warning_within_rows():
    ctx = _make_context(item=_charm_item())
    _place(ctx, HOLDER, FactionType.ALLY, 3)

    assert _check_charm_row_capacity(_state_with(ctx)) is None
