import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import logging  # noqa: E402

from battle.core.commands.define import RoundPhaseType  # noqa: E402
from battle.objects.define import (  # noqa: E402
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
)
from battle.objects.models import CharacterId  # noqa: E402
from battle.practice.define import (  # noqa: E402
    PracticeBattleMode,
    PracticeRoundPhase,
    SideType,
)
from bot import field_restore  # noqa: E402
from bot.log_sheets import FieldBattleType, FieldRow  # noqa: E402
from bot.main import BotState  # noqa: E402
from helpers import get_test_preset  # noqa: E402


def _make_state(name_dict: dict) -> BotState:
    return BotState(
        char_dict={},
        name_dict=name_dict,
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )


def test_restore_main_battle_reconstructs_session_progress():
    state = _make_state(
        {
            "아군1": get_test_preset("아군1", initial_hp=50),
            "적1": get_test_preset("적1", initial_hp=30),
        }
    )
    row = FieldRow(
        field_id="999",
        battle_type=FieldBattleType.MAIN,
        round_n=3,
        phase=RoundPhaseType.ALLY_ACTION.value,
        characters=[
            {"name": "아군1", "faction": "아군", "position": 1, "remaining_cost": 1},
            {"name": "적1", "faction": "적군", "position": 2, "remaining_cost": 2},
        ],
        meta={"name": "복원 테스트 전투", "active_phase_post_id": 777},
    )

    summary = field_restore._restore_main_battle(state, row, {}, {}, {}, {}, None)

    assert summary is not None
    assert state.session is not None
    assert state.session.started is True
    assert state.session.round_n == 3
    assert state.session.current_phase == RoundPhaseType.ALLY_ACTION
    assert state.session.name == "복원 테스트 전투"
    assert state.preparation_status_id == 999
    assert state.active_phase_post_id == 777

    ally = state.session.context.characters[CharacterId("아군1")]
    assert ally.status.remaining_cost == 1
    enemy = state.session.context.characters[CharacterId("적1")]
    assert enemy.faction == FactionType.ENEMY
    assert enemy.status.remaining_cost == 2


def test_restore_main_battle_skips_unknown_character(caplog):
    """ "캐릭터"/"에너미" 시트에 없는 이름(소환수 등)은 조용히 건너뛰고 경고만
    남겨야 한다 — 복원 자체가 실패하면 안 된다."""
    state = _make_state({"아군1": get_test_preset("아군1")})
    row = FieldRow(
        field_id="999",
        battle_type=FieldBattleType.MAIN,
        round_n=1,
        phase=RoundPhaseType.ENEMY_PRE_ACTION.value,
        characters=[
            {"name": "아군1", "faction": "아군", "position": 1, "remaining_cost": 3},
            {
                "name": "동료소환수",
                "faction": "아군",
                "position": 1,
                "remaining_cost": 3,
            },
        ],
        meta={},
    )

    with caplog.at_level(logging.WARNING, logger="bot.field_restore"):
        summary = field_restore._restore_main_battle(state, row, {}, {}, {}, {}, None)

    assert summary is not None
    assert CharacterId("아군1") in state.session.context.characters
    assert CharacterId("동료소환수") not in state.session.context.characters
    assert any("동료소환수" in r.getMessage() for r in caplog.records)


def test_restore_main_battle_fails_when_no_character_restorable():
    state = _make_state({})
    row = FieldRow(
        field_id="999",
        battle_type=FieldBattleType.MAIN,
        round_n=1,
        phase=RoundPhaseType.ENEMY_PRE_ACTION.value,
        characters=[
            {
                "name": "동료소환수",
                "faction": "아군",
                "position": 1,
                "remaining_cost": 3,
            }
        ],
        meta={},
    )

    summary = field_restore._restore_main_battle(state, row, {}, {}, {}, {}, None)

    assert summary is None
    assert state.session is None


def test_restore_investigation_session_menu_stage():
    """개요 게시물 이전(메뉴 답글 대기 중)에 재기동해도 acct/menu_post_id만
    으로 세션을 복원할 수 있어야 한다."""
    state = _make_state({})
    row = FieldRow(
        field_id="100",
        battle_type=FieldBattleType.INVESTIGATION_QUEST,
        round_n=0,
        phase="",
        characters=[],
        meta={"acct": "user1", "menu_post_id": 100},
    )

    summary = field_restore._restore_investigation_session(state, row)

    assert summary is not None
    session = state.noncombat.investigations["user1"]
    assert session.field_id == "100"
    assert session.menu_post_id == 100
    assert session.overview_post_id is None
    assert session.quest_id is None
    assert session.ended is False


def test_restore_investigation_session_overview_stage():
    """의뢰 개요까지 진행된 뒤 재기동하면 overview_post_id/quest_id도
    함께 복원돼야 한다."""
    state = _make_state({})
    row = FieldRow(
        field_id="100",
        battle_type=FieldBattleType.INVESTIGATION_QUEST,
        round_n=0,
        phase="",
        characters=[],
        meta={
            "acct": "user1",
            "menu_post_id": 100,
            "overview_post_id": 200,
            "quest_id": "아도스_운반",
        },
    )

    summary = field_restore._restore_investigation_session(state, row)

    assert summary is not None
    session = state.noncombat.investigations["user1"]
    assert session.overview_post_id == 200
    assert session.quest_id == "아도스_운반"


def test_restore_investigation_session_skips_when_meta_missing():
    state = _make_state({})
    row = FieldRow(
        field_id="100",
        battle_type=FieldBattleType.INVESTIGATION_QUEST,
        round_n=0,
        phase="",
        characters=[],
        meta={},
    )

    summary = field_restore._restore_investigation_session(state, row)

    assert summary is None
    assert state.noncombat.investigations == {}


def test_restore_practice_battle_restores_hp_and_movers():
    state = _make_state(
        {
            "선공캐릭터": get_test_preset("선공캐릭터", max_hp=100),
            "후공캐릭터": get_test_preset("후공캐릭터", max_hp=100),
        }
    )
    row = FieldRow(
        field_id="prep-123",
        battle_type=FieldBattleType.PRACTICE,
        round_n=2,
        phase=PracticeRoundPhase.SECOND_MOVER_ACTION.value,
        characters=[
            {
                "name": "선공캐릭터",
                "faction": "아군",
                "position": 1,
                "remaining_cost": 2,
                "curr_hp": 37,
            },
            {
                "name": "후공캐릭터",
                "faction": "적군",
                "position": 2,
                "remaining_cost": 3,
                "curr_hp": 12,
            },
        ],
        meta={
            "prep_post_id": 123,
            "active_post_id": 456,
            "visibility": "public",
            "round_limit": 5,
            "first_mover": SideType.SIDE_1.value,
            "second_mover": SideType.SIDE_2.value,
        },
    )

    summary = field_restore._restore_practice_battle(state, row, {}, {}, {}, {})

    assert summary is not None
    assert 456 in state.practices
    ps = state.practices[456]
    assert ps.round_n == 2
    assert ps.round_limit == 5
    # 라운드 시작 후에는 항상 0이어야 한다 — 포지션 선언 접수 단계로 잘못
    # 되돌아가면 안 된다.
    assert ps.prep_post_id == 0
    assert ps.active_post_id == 456
    assert ps.first_mover == SideType.SIDE_1
    assert ps.second_mover == SideType.SIDE_2
    assert ps.phase == PracticeRoundPhase.SECOND_MOVER_ACTION

    first = ps.context.characters[CharacterId("선공캐릭터")]
    assert first.status.curr_hp == 37
    second = ps.context.characters[CharacterId("후공캐릭터")]
    assert second.status.curr_hp == 12


def test_restore_practice_battle_marks_investigation_type():
    state = _make_state({"아군1": get_test_preset("아군1")})
    row = FieldRow(
        field_id="prep-1",
        battle_type=FieldBattleType.INVESTIGATION,
        round_n=1,
        phase=PracticeRoundPhase.FIRST_MOVER_ACTION.value,
        characters=[
            {
                "name": "아군1",
                "faction": "아군",
                "position": 1,
                "remaining_cost": 3,
                "curr_hp": 20,
            }
        ],
        meta={
            "active_post_id": 789,
            "first_mover": SideType.SIDE_1.value,
            "second_mover": SideType.SIDE_2.value,
        },
    )

    field_restore._restore_practice_battle(state, row, {}, {}, {}, {})

    assert state.practices[789].is_investigation is True


def test_restore_duel_keeps_full_hp_and_no_round_limit():
    """결투 행은 최대 체력 그대로 복원되고 라운드 상한이 다시 생기지 않아야
    한다 — 상한이 붙으면 재기동 직후 라운드 하나로 끝나 버린다."""
    state = _make_state({"1팀캐릭터": get_test_preset("1팀캐릭터", max_hp=100)})
    row = FieldRow(
        field_id="prep-duel",
        battle_type=FieldBattleType.DUEL,
        round_n=4,
        phase=PracticeRoundPhase.FIRST_MOVER_ACTION.value,
        characters=[
            {
                "name": "1팀캐릭터",
                "faction": "아군",
                "position": 1,
                "remaining_cost": 3,
                "curr_hp": 55,
            }
        ],
        meta={
            "active_post_id": 321,
            "first_mover": SideType.SIDE_1.value,
            "second_mover": SideType.SIDE_2.value,
            "roster": {SideType.SIDE_1.value: ["1팀캐릭터", "기권한캐릭터"]},
        },
    )

    field_restore._restore_practice_battle(state, row, {}, {}, {}, {})

    ps = state.practices[321]
    assert ps.mode == PracticeBattleMode.DUEL
    assert ps.round_limit is None
    character = ps.context.characters[CharacterId("1팀캐릭터")]
    assert character.status[CombatStatType.MAX_HP] == 100
    assert character.status.curr_hp == 55
    # 자진 기권해 필드에 없는 캐릭터도 패배 대가 대상으로 남아야 한다.
    assert ps.roster_by_side[SideType.SIDE_1] == ["1팀캐릭터", "기권한캐릭터"]


def test_restore_practice_battle_fails_when_active_post_id_missing():
    """active_post_id 메타가 없으면 state.practices에 등록할 키가 없으므로
    복원을 포기해야 한다."""
    state = _make_state({"아군1": get_test_preset("아군1")})
    row = FieldRow(
        field_id="prep-1",
        battle_type=FieldBattleType.PRACTICE,
        round_n=1,
        phase=PracticeRoundPhase.FIRST_MOVER_ACTION.value,
        characters=[],
        meta={
            "first_mover": SideType.SIDE_1.value,
            "second_mover": SideType.SIDE_2.value,
        },
    )

    summary = field_restore._restore_practice_battle(state, row, {}, {}, {}, {})

    assert summary is None
    assert not state.practices


def test_restore_practice_battle_restores_multiple_concurrent_sessions():
    """대련/상시전투는 동시에 여러 개가 진행될 수 있으므로, 이미 하나를
    복원한 뒤에도 다른 열린 대련/상시전투 행이 있으면 함께 복원돼야 한다."""
    state = _make_state(
        {"아군1": get_test_preset("아군1"), "아군2": get_test_preset("아군2")}
    )
    row1 = FieldRow(
        field_id="prep-1",
        battle_type=FieldBattleType.PRACTICE,
        round_n=1,
        phase=PracticeRoundPhase.FIRST_MOVER_ACTION.value,
        characters=[
            {"name": "아군1", "faction": "아군", "position": 1, "remaining_cost": 1}
        ],
        meta={
            "active_post_id": 111,
            "first_mover": SideType.SIDE_1.value,
            "second_mover": SideType.SIDE_2.value,
        },
    )
    row2 = FieldRow(
        field_id="prep-2",
        battle_type=FieldBattleType.PRACTICE,
        round_n=1,
        phase=PracticeRoundPhase.FIRST_MOVER_ACTION.value,
        characters=[
            {"name": "아군2", "faction": "아군", "position": 1, "remaining_cost": 1}
        ],
        meta={
            "active_post_id": 222,
            "first_mover": SideType.SIDE_1.value,
            "second_mover": SideType.SIDE_2.value,
        },
    )

    summary1 = field_restore._restore_practice_battle(state, row1, {}, {}, {}, {})
    summary2 = field_restore._restore_practice_battle(state, row2, {}, {}, {}, {})

    assert summary1 is not None
    assert summary2 is not None
    assert set(state.practices) == {111, 222}
    assert state.practices[111].field_id == "prep-1"
    assert state.practices[222].field_id == "prep-2"


def test_restore_all_skips_unrestorable_rows(monkeypatch):
    """load_open_battle_rows가 반환한 행 중 하나가 복원 불가해도, 나머지
    행 복원은 계속 진행되어야 한다."""
    state = _make_state({"아군1": get_test_preset("아군1")})

    rows = [
        FieldRow(
            field_id="999",
            battle_type=FieldBattleType.MAIN,
            round_n=1,
            phase=RoundPhaseType.ENEMY_PRE_ACTION.value,
            characters=[
                {"name": "아군1", "faction": "아군", "position": 1, "remaining_cost": 3}
            ],
            meta={},
        ),
        FieldRow(
            field_id="practice-broken",
            battle_type=FieldBattleType.PRACTICE,
            round_n=1,
            phase="알 수 없는 페이즈",
            characters=[],
            meta={"active_post_id": 1},
        ),
    ]
    monkeypatch.setattr(
        field_restore, "load_open_battle_rows", lambda spreadsheet: rows
    )

    summaries = field_restore.restore_all(state, {}, {}, {}, {}, None)

    assert len(summaries) == 1
    assert state.session is not None


def test_restore_practice_prep_stage_keeps_declared_positions():
    """포지션 선언 단계(라운드가 아직 안 열린 행)도 복원된다.

    이 행이 없던 시절에는 [대련] 직후의 상태가 메모리에만 있어, 봇을 다시
    올리는 순간 참가자가 [대련]부터 다시 시작해야 했다."""
    state = _make_state({})
    row = FieldRow(
        field_id="prep-9",
        battle_type=FieldBattleType.DUEL,
        round_n=0,
        phase="",
        characters=[],
        meta={
            # mastodon.py가 돌려주는 게시물 id는 문자열이다 — 복원도 같은
            # 형태로 키를 만들어야 답글이 매칭된다.
            "prep_post_id": "9001",
            "active_post_id": None,
            "visibility": "unlisted",
            "expected_accts": ["acct_a", "acct_b"],
            "positions": {"acct_a": [SideType.SIDE_1.value, 2]},
        },
    )

    summary = field_restore._restore_practice_battle(state, row, {}, {}, {}, {})

    assert summary is not None
    assert "9001" in state.practices
    ps = state.practices["9001"]
    assert ps.mode == PracticeBattleMode.DUEL
    assert ps.prep_post_id == "9001"
    assert ps.active_post_id is None
    assert ps.field_id == "prep-9"
    assert ps.visibility == "unlisted"
    assert ps.expected_accts == ["acct_a", "acct_b"]
    assert ps.declared == {"acct_a": (SideType.SIDE_1, BattlefieldColumnIndex(2))}
    # 아직 한 명이 남았으므로 전투를 시작할 수 있는 상태가 아니다.
    assert ps.all_declared() is False


def test_restore_practice_prep_stage_skips_broken_position_entries(caplog):
    """포지션 한 건이 깨졌다고 세션 전체를 포기하지는 않는다 — 그 참가자만
    다시 선언하면 된다."""
    state = _make_state({})
    row = FieldRow(
        field_id="prep-9",
        battle_type=FieldBattleType.PRACTICE,
        round_n=0,
        phase="",
        characters=[],
        meta={
            "prep_post_id": "9002",
            "expected_accts": ["acct_a", "acct_b"],
            "positions": {
                "acct_a": [SideType.SIDE_1.value, 0],
                "acct_b": ["없는팀", 99],
            },
        },
    )

    with caplog.at_level(logging.WARNING):
        summary = field_restore._restore_practice_battle(state, row, {}, {}, {}, {})

    assert summary is not None
    assert set(state.practices["9002"].declared) == {"acct_a"}


def test_restore_practice_prep_stage_fails_without_participants():
    """참여 대상 메타가 없으면 누가 선언할 수 있는지 알 수 없어 복원을
    포기한다 — 빈 명부로 살려 두면 아무도 진행할 수 없는 세션이 남는다."""
    state = _make_state({})
    row = FieldRow(
        field_id="prep-9",
        battle_type=FieldBattleType.PRACTICE,
        round_n=0,
        phase="",
        characters=[],
        meta={"prep_post_id": "9003"},
    )

    assert field_restore._restore_practice_battle(state, row, {}, {}, {}, {}) is None
    assert not state.practices


def _buff_snapshot_context(buff_dict: dict):
    """버프 스냅샷/복원 테스트용 최소 전장 — 캐릭터 둘을 1열에 세운다."""
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.define import BattlefieldColumnIndex

    ctx = BattlefieldContext(buff_dict=buff_dict, skill_dict={})
    ctx.add_character(
        get_test_preset("아군1"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx


def _stacking_buff_dict() -> dict:
    from battle.objects.buff.models import BuffData

    return {
        "적층표식": BuffData.from_dict(
            {
                "id": "적층표식",
                "buff_name": "BuffStackingMark",
                "duration_turn_value": 3,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": "",
                "value_type_0": "",
                "condition": "",
                "condition_value": "",
                "description": "",
                "type": "디버프",
                "max_stack": 3,
            }
        ),
    }


def test_field_snapshot_carries_buff_state():
    """캐릭터 스냅샷에 남은 턴과 스택까지 담겨야 복원이 "다시 부여"가 아니라
    "그 상태 그대로 이어받기"가 된다."""
    from battle.objects.buff.buff_base import BuffAddData
    from bot.log_sheets import build_field_characters

    ctx = _buff_snapshot_context(_stacking_buff_dict())
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("아군1"),
            applied_to=CharacterId("적1"),
            buff_id="적층표식",
            stack_value=2,
        )
    )
    ctx.buff_container.get_buffs_by(CharacterId("적1"), None)[
        0
    ].duration.remaining_turns = 1

    rows = build_field_characters(ctx, include_hp=True)
    enemy_row = next(r for r in rows if r["name"] == "적1")
    ally_row = next(r for r in rows if r["name"] == "아군1")

    assert enemy_row["buffs"] == [
        {"id": "적층표식", "given_by": "아군1", "stack": 2, "turns": 1, "seq": 1}
    ]
    assert "buffs" not in ally_row


def test_restore_buffs_keeps_remaining_turns_and_stack():
    """복원은 남은 턴을 시트 값(3턴)으로 리셋하지 않고 스냅샷 값을 쓴다."""
    ctx = _buff_snapshot_context(_stacking_buff_dict())
    characters = [
        {
            "name": "적1",
            "buffs": [{"id": "적층표식", "given_by": "아군1", "stack": 2, "turns": 1}],
        }
    ]

    assert field_restore._restore_buffs(ctx, characters) == 1

    buffs = ctx.buff_container.get_buffs_by(CharacterId("적1"), None)
    assert len(buffs) == 1
    assert buffs[0].id == "적층표식"
    assert buffs[0].given_by == CharacterId("아군1")
    assert buffs[0].stack_count == 2
    assert buffs[0].duration.remaining_turns == 1


def test_restore_buffs_skips_unknown_id_and_absent_target(caplog):
    """시트에서 사라진 버프 id나 필드에 없는 대상은 그 항목만 건너뛴다 —
    전투 복원 전체를 포기하지 않는다."""
    ctx = _buff_snapshot_context(_stacking_buff_dict())
    characters = [
        {"name": "적1", "buffs": [{"id": "없는버프", "given_by": "아군1"}]},
        {"name": "필드에없음", "buffs": [{"id": "적층표식", "given_by": "아군1"}]},
    ]

    with caplog.at_level(logging.WARNING):
        assert field_restore._restore_buffs(ctx, characters) == 0

    assert not ctx.buff_container.get_buffs_by(CharacterId("적1"), None)


def test_restore_buffs_overwrites_a_buff_reapplied_by_battle_start():
    """ "전투 시작" 트리거가 복원보다 먼저 같은 버프를 걸어 두었어도, 인스턴스를
    새로 만들지 않고 스냅샷 값으로 맞춘다 — 그러지 않으면 지속시간이 시트 값
    그대로 남아 남은 턴이 스냅샷보다 늘어난다."""
    from battle.objects.buff.buff_base import BuffAddData

    ctx = _buff_snapshot_context(_stacking_buff_dict())
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("아군1"),
            applied_to=CharacterId("적1"),
            buff_id="적층표식",
        )
    )
    assert (
        ctx.buff_container.get_buffs_by(CharacterId("적1"), None)[
            0
        ].duration.remaining_turns
        == 3
    )

    field_restore._restore_buffs(
        ctx,
        [
            {
                "name": "적1",
                "buffs": [
                    {"id": "적층표식", "given_by": "아군1", "stack": 3, "turns": 1}
                ],
            }
        ],
    )

    buffs = ctx.buff_container.get_buffs_by(CharacterId("적1"), None)
    assert len(buffs) == 1
    assert buffs[0].stack_count == 3
    assert buffs[0].duration.remaining_turns == 1
