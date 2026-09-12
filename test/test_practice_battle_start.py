"""대련/상시전투에서 "전투 시작" 트리거 패시브가 실제로 발동하는지 검증한다.

배경: 본 전투는 BattleSession이 배치 직후 context.on_battle_start()를 부르지만
(bot/session.py), 대련/상시전투는 그 지점이 아예 없어서 BATTLE_START 트리거를
쓰는 패시브(전투 시작 시 소환수를 부르는 패시브 등)가 한 번도 평가되지
않았다."""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.objects.buff.models import BuffData  # noqa: E402
from battle.objects.define import BattlefieldColumnIndex  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.objects.passive_skill.models import PassiveSkillData  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import SideType  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot import main as main_module  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402
from helpers import get_test_preset  # noqa: E402

PASSIVE_ID = "PassiveSkill"
MARK_BUFF_ID = "표식"


def _mark_buff() -> BuffData:
    return BuffData.from_dict(
        {
            "id": MARK_BUFF_ID,
            "buff_name": "BuffStackingMark",
            "duration_turn_value": "",
            "duration_count_value": "",
            "duration_count_deduct_condition": "",
            "value_0": "",
            "value_type_0": "",
            "value_1": "",
            "value_type_1": "",
            "condition": "",
            "condition_value": "",
            "type": "버프",
            "max_stack": 3,
            "reference_buff_id": "",
            "description": "",
        }
    )


def _battle_start_passive() -> PassiveSkillData:
    return PassiveSkillData.from_dict(
        {
            "id": PASSIVE_ID,
            "description": "",
            "trigger": "전투 시작",
            "target_type": "자신",
            "buff_id": "",
            "effect_0": "SkillEffectAddBuff",
            "value_source_0": "",
            "value_0": "",
            "value_type_0": "",
            "buff_id_0": MARK_BUFF_ID,
            "target_override_0": "자신",
            "condition_0": "",
            "condition_value_0": "",
        },
        passive_buff_dict={},
    )


def test_battle_start_passive_fires_in_practice_context():
    ctx = PracticeBattlefieldContext(
        buff_dict={MARK_BUFF_ID: _mark_buff()},
        skill_dict={},
        passive_skill_dict={PASSIVE_ID: _battle_start_passive()},
    )
    ctx.add_character(
        get_test_preset("A", passive_skill_id=PASSIVE_ID),
        SideType.SIDE_1,
        BattlefieldColumnIndex(0),
    )
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))

    holder = CharacterId("A")
    assert ctx.buff_container.get_buff(holder, MARK_BUFF_ID) is None

    ctx.on_battle_start()

    assert ctx.buff_container.get_buff(holder, MARK_BUFF_ID) is not None


def _state_and_session():
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ps = PracticeBattleState(
        context=ctx,
        manager=PracticeRoundManager(ctx),
        declared={
            "acct_a": (SideType.SIDE_1, BattlefieldColumnIndex(0)),
            "acct_b": (SideType.SIDE_2, BattlefieldColumnIndex(0)),
        },
    )
    state = BotState(
        char_dict={"acct_a": get_test_preset("A"), "acct_b": get_test_preset("B")},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    return ctx, ps, state


def _record_on_battle_start(monkeypatch, ctx) -> list[int]:
    """on_battle_start()이 불린 시점의 배치 인원 수를 기록한다 — 배치보다
    먼저 불리면 소환수 계열 패시브가 전장을 보지 못한다."""
    placed_when_called: list[int] = []
    monkeypatch.setattr(
        ctx,
        "on_battle_start",
        lambda: placed_when_called.append(len(ctx.characters)),
        raising=False,
    )
    return placed_when_called


def test_practice_start_calls_on_battle_start_after_placement(monkeypatch):
    ctx, ps, state = _state_and_session()
    placed_when_called = _record_on_battle_start(monkeypatch, ctx)

    main_module._start_practice_battle(state, ps)

    assert placed_when_called == [2]


def test_investigation_start_calls_on_battle_start_after_placement(monkeypatch):
    ctx, ps, state = _state_and_session()
    ps.is_investigation = True
    placed_when_called = _record_on_battle_start(monkeypatch, ctx)

    main_module._start_investigation_battle(state, ps)

    assert placed_when_called == [2]
