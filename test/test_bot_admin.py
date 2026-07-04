import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

from battle.objects.define import BattlefieldColumnIndex, FactionType  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.practice.define import SideType  # noqa: E402
from bot.commands import admin as admin_module  # noqa: E402
from bot.commands.admin import _cmd_battle_start  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.session import BattleSession  # noqa: E402
from helpers import get_test_preset  # noqa: E402


def _make_state(**pending) -> BotState:
    state = BotState(
        buff_dict={},
        skill_dict={},
        passive_skill_dict={},
        item_dict={},
        inventory=None,
        char_dict={},
        name_dict={"유효 캐릭터": get_test_preset("유효 캐릭터")},
        noncombat_char_dict={},
        spreadsheet=None,
    )
    state.session = BattleSession(buff_dict={}, skill_dict={})
    state.pending_placements = pending.get("pending_placements", [])
    state.pending_participants = pending.get("pending_participants", [])
    return state


def test_battle_does_not_start_when_all_placements_fail():
    """모든 배치가 실패(존재하지 않는 캐릭터 등)하면 전투가 시작되면 안 된다."""
    state = _make_state(
        pending_placements=[
            ("존재하지 않는 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0))
        ]
    )

    result = _cmd_battle_start(state)

    assert state.session.started is False
    assert len(state.session.context.characters) == 0
    assert "시작하지 못했습니다" in result.reply_text


def test_battle_starts_when_at_least_one_placement_succeeds():
    """일부 배치만 성공해도(캐릭터 1명 이상) 전투는 정상적으로 시작되어야 한다."""
    state = _make_state(
        pending_placements=[
            ("유효 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(0)),
            ("존재하지 않는 캐릭터", FactionType.ALLY, BattlefieldColumnIndex(1)),
        ]
    )

    result = _cmd_battle_start(state)

    assert state.session.started is True
    assert len(state.session.context.characters) == 1
    assert "전투 시작" in result.reply_text


def test_investigation_battle_inline_placement_respects_faction_token(monkeypatch):
    """[상시전투]와 함께 입력된 [배치/이름/아군 3열]은 '아군' 토큰대로
    SIDE_1(아군)에 배치되어야 하며, 무조건 적(SIDE_2)으로 배치되면 안 된다."""
    state = _make_state()
    state.name_dict = {"동료": get_test_preset("동료")}
    monkeypatch.setattr(
        admin_module,
        "load_char_data",
        lambda spreadsheet: (state.char_dict, state.name_dict, state.noncombat_char_dict),
    )

    result = admin_module._cmd_investigation_battle(
        "[상시전투][배치/동료/아군 3열]", [], state
    )

    assert not result.reply_text or "오류" not in (result.game_post_text or "")
    char_id = CharacterId("동료")
    assert char_id in state.practice.context.characters
    assert state.practice.context.get_side(char_id) == SideType.SIDE_1
