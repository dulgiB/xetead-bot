"""대련/결투/상시전투 진행 공지는 필드 보드까지만 싣고, 버프/디버프 목록은
"버프 목록" CW 후속 게시물로 따로 보낸다 — 목록이 길어도 공지가 잘리지 않는다."""

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
from battle.practice.define import SideType  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot.main import (  # noqa: E402
    _MAX_POST_LENGTH,
    MastodonBotListener,
    _field_board,
)
from bot.practice_state import PracticeBattleState  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from test_bot_admin import _FakeMastodon, _make_state  # noqa: E402


def _ps(description: str = "받는 대미지가 증가한다.") -> PracticeBattleState:
    buff = BuffData(
        id="취약",
        buff_class_name="BuffReceivedDamage",
        duration_turn_value=2,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=10,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.DEBUFF,
        description=description,
    )
    ctx = PracticeBattlefieldContext(buff_dict={"취약": buff}, skill_dict={})
    ctx.add_character(get_test_preset("A"), SideType.SIDE_1, BattlefieldColumnIndex(0))
    ctx.add_character(get_test_preset("B"), SideType.SIDE_2, BattlefieldColumnIndex(0))
    ctx.buff_container.add(
        BuffAddData(
            given_by=CharacterId("A"), applied_to=CharacterId("B"), buff_id="취약"
        )
    )
    return PracticeBattleState(
        context=ctx, manager=PracticeRoundManager(ctx), visibility="unlisted"
    )


def _post(ps: PracticeBattleState, game_post: str, *, ended: bool = False):
    mastodon = _FakeMastodon()
    listener = MastodonBotListener(mastodon, _make_state(), bot_acct="bot")
    last = listener._post_practice_game_post(ps, game_post, 1, ["a"], ended)
    return mastodon.status_post_calls, last


def test_buff_list_goes_to_folded_followup():
    ps = _ps()
    calls, last = _post(ps, f"◊ [2라운드] 선공\n\n{_field_board(ps)}")

    main, followup = calls
    assert "[취약]" not in main["status"]
    assert "spoiler_text" not in main
    assert followup["spoiler_text"] == "버프 목록"
    assert "[취약]" in followup["status"]
    assert followup["in_reply_to_id"] == last["id"]
    assert followup["visibility"] == "unlisted"


def test_no_followup_when_battle_ended():
    calls, _ = _post(_ps(), "◊ 상시전투 종료", ended=True)

    assert len(calls) == 1


def test_long_game_post_is_split_instead_of_truncated():
    ps = _ps()
    long_log = "\n".join(f"▹ 대상_{i} | -10 → 90/100" for i in range(60))
    calls, last = _post(ps, f"{long_log}\n\n{_field_board(ps)}")

    mains = [c for c in calls if "spoiler_text" not in c]
    assert len(mains) > 1
    assert all(len(c["status"]) <= _MAX_POST_LENGTH for c in mains)
    assert "대상_59" in mains[-1]["status"]
    assert not any(c["status"].endswith("…") for c in mains)
    assert calls[-1]["in_reply_to_id"] == last["id"]
