"""대련/결투에서 동료를 가진 캐릭터가 자진 기권([탈락])할 때의 정리.

`remove_character()`는 그 캐릭터만 내린다. 소환자가 그렇게 빠지면 동료는
`characters`에 남은 채 `companion_owners`가 사라진 주인을 가리키고,
`find_character_position()`이 owner를 따라가다 예외를 던진다 — 그 뒤로 이
세션의 "필드" 시트 저장(`build_field_characters`)이 매번 실패해 재기동 복원
스냅샷이 낡은 채로 멈춘다(2026-09-13 실제 대련에서 발생).

admin의 `[탈락/이름]`은 `force_remove_character()`를 써서 동료까지 함께
내리고 있었으므로, 자진 기권도 같은 경로를 타야 한다.
"""

import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

from battle.objects.define import BattlefieldColumnIndex  # noqa: E402
from battle.objects.models import CharacterId  # noqa: E402
from battle.practice.context import PracticeBattlefieldContext  # noqa: E402
from battle.practice.define import SideType  # noqa: E402
from battle.practice.round_manager import PracticeRoundManager  # noqa: E402
from bot import log_sheets  # noqa: E402
from bot import main as main_module  # noqa: E402
from bot.main import BotState  # noqa: E402
from bot.practice_state import PracticeBattleState  # noqa: E402
from helpers import get_test_preset  # noqa: E402

OWNER = CharacterId("Catastrophe")
FOE = CharacterId("Adversary")
COMPANION_BUFF = "동료"


def _state() -> tuple[PracticeBattlefieldContext, PracticeBattleState, BotState]:
    ctx = PracticeBattlefieldContext(buff_dict={}, skill_dict={})
    ctx.add_character(
        get_test_preset(OWNER.name), SideType.SIDE_1, BattlefieldColumnIndex(3)
    )
    ctx.add_character(
        get_test_preset(FOE.name), SideType.SIDE_2, BattlefieldColumnIndex(3)
    )
    ctx.spawn_companion_if_absent(OWNER, COMPANION_BUFF, 10)
    ps = PracticeBattleState(
        context=ctx,
        manager=PracticeRoundManager(ctx),
        active_post_id=1,
        field_id="1",
    )
    state = BotState(
        char_dict={"owner_acct": get_test_preset(OWNER.name)},
        name_dict={},
        noncombat_char_dict={},
        spreadsheet=None,
        field_spreadsheet=None,
        log_spreadsheet=None,
    )
    return ctx, ps, state


def test_retiring_owner_takes_the_companion_off_the_field(monkeypatch):
    monkeypatch.setattr(main_module, "_upsert_practice_field_row", lambda *a, **k: None)
    monkeypatch.setattr(
        main_module, "_finalize_practice_phase", lambda *a, **k: (None, False)
    )
    ctx, ps, state = _state()
    companion_id = ctx.find_companion_id(OWNER)
    assert companion_id is not None and companion_id in ctx.characters

    reply, _calc, _post, _log, _ended = main_module._handle_practice_command(
        "owner_acct", "[탈락]", state, ps
    )

    assert OWNER not in ctx.characters
    assert companion_id not in ctx.characters
    assert companion_id.name in (reply or "")
    # 필드 스냅샷이 다시 만들어져야 한다 — 주인 잃은 동료가 남으면 여기서 터진다.
    assert log_sheets.build_field_characters(ctx, include_hp=True)
