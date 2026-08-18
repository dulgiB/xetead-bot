import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import random  # noqa: E402
from datetime import date  # noqa: E402

import pytest  # noqa: E402
from battle.objects.define import ItemType, ValueSourceType, ValueType  # noqa: E402
from battle.objects.item.models import ItemData  # noqa: E402
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectHeal  # noqa: E402
from bot import commands as _  # noqa: E402, F401
from bot.commands import noncombat as noncombat_module  # noqa: E402
from bot.commands.noncombat import (  # noqa: E402
    finalize_daily_quest_mid,
    handle_1d100,
    handle_bag,
    handle_daily_quest_roll,
    handle_daily_quest_start,
    handle_investigation_accept,
    handle_investigation_decline,
    handle_investigation_start,
    handle_investigation_venue_choice,
    handle_roll,
    handle_transfer_item,
    handle_use_item,
    parse_transfer_item_args,
    parse_use_item_args,
)
from bot.main import BotState  # noqa: E402
from bot.main import _restore_daily_quest_mid_state  # noqa: E402
from bot.noncombat_state import DailyQuestMidState  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from spreadsheets.inventory import Inventory  # noqa: E402
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet  # noqa: E402
from spreadsheets.models.quest import (  # noqa: E402
    DailyQuestPools,
    DailyQuestResultMessageData,
    DailyQuestSuccessType,
    QuestData,
    QuestLocationData,
)


def _make_state(acct: str) -> BotState:
    state = BotState(
        char_dict={acct: get_test_preset("동료")},
        name_dict={},
        noncombat_char_dict={
            acct: NoncombatCharacterDataFromSpreadsheet(
                name="동료", stat_physical=2, gold=10, daily_quest_date=""
            )
        },
        spreadsheet=None,
        field_spreadsheet=None,
    )
    state.noncombat.daily_quest_mid[acct] = DailyQuestMidState(bot_reply_post_id=123)
    return state


def _daily_quest_pools(
    client_categories=("길 잃은",),
    client_names=("어린아이로부터",),
    quest_contents=("부모를 찾아 달라는",),
) -> DailyQuestPools:
    return DailyQuestPools(
        client_categories=list(client_categories),
        client_names=list(client_names),
        quest_contents=list(quest_contents),
    )


def test_handle_roll_returns_log_info():
    """[판정/스탯]은 예전에는 "로그_비전투"에 전혀 기록되지 않았다 — 이제는
    항상 NoncombatLogInfo를 반환해야 한다."""
    acct = "user1"
    state = _make_state(acct)

    result, log_info = handle_roll(acct, "육체", state)

    assert "「" in result
    assert log_info is not None
    assert log_info.command_text == "[판정/육체]"
    assert log_info.dice_roll
    assert log_info.error_trace is None


def test_handle_roll_reply_labels_dice_part_with_1d6(monkeypatch):
    """전투 대미지 굴림 표시("4 + 1[1d6]", 기본값이 먼저 오고 주사위가
    나중)와 일관되게, [판정/스탯]의 계산식도 "◊ 판정: {스탯값}[{스탯명}] +
    {주사위}[1d6] → 「합계」" 형식으로 표시해 스탯값과 주사위 굴림을
    시각적으로 구분해야 한다."""
    acct = "user1"
    state = _make_state(acct)  # stat_physical=2
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    result, _log_info = handle_roll(acct, "육체", state)

    assert "◊ 판정: 2[육체] + 6[1d6] → 「8」" in result


def _quest_location(
    location_id: str = "아도스",
    active: bool = True,
    description: str = "항구 마을이다.",
) -> QuestLocationData:
    return QuestLocationData(id=location_id, active=active, description=description)


def _quest(
    location_id: str = "아도스",
    quest_type: str = "운반",
    venue: str = "광장",
    name: str = "광장 의뢰",
    description: str = "어쩌구",
    subtype: str = "상시",
    reward: str = "6G",
    available_until: str = "다음 스토리 진행 전까지",
    taken_by: str = "",
) -> QuestData:
    return QuestData(
        id=f"{location_id}_{quest_type}",
        active=False,
        location=venue,
        name=name,
        description=description,
        type=quest_type,
        subtype=subtype,
        reward=reward,
        available_until=available_until,
        taken_by=taken_by,
    )


def test_handle_investigation_accept_returns_log_info(monkeypatch):
    """[수락]도 마찬가지로 NoncombatLogInfo를 반환해 로그에 남아야 한다."""
    acct = "user1"
    state = _make_state(acct)
    state.noncombat.investigation_overview_quest[999] = "아도스_운반"
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest()]),
    )
    monkeypatch.setattr(noncombat_module, "update_quest_taken_by", lambda *a, **k: None)

    result, log_info = handle_investigation_accept(acct, [], state, in_reply_to_id=999)

    assert "의뢰를 받았다" in result
    assert log_info is not None
    assert log_info.command_text == "[수락]"


def test_investigation_accept_writes_taken_by_and_registers_mentions(monkeypatch):
    """[수락] 답글에 멘션된 인원 전원(+ 발신자)이 참여자로 등록되고, '일반 의뢰'
    시트의 taken_by에 쉼표로 이어붙여 기록되어야 한다."""
    acct = "user1"
    state = _make_state(acct)
    state.noncombat.investigation_overview_quest[999] = "아도스_운반"
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest()]),
    )
    calls = []
    monkeypatch.setattr(
        noncombat_module,
        "update_quest_taken_by",
        lambda spreadsheet, quest_id, taken_by, cache=None: calls.append(
            (quest_id, taken_by)
        ),
    )

    result, log_info = handle_investigation_accept(
        acct, ["user2", "user3"], state, in_reply_to_id=999
    )

    # 참여자 전원 멘션은 handle_investigation_accept 자체가 아니라 main.py의
    # _reply(mention_accts=...)가 게시물 맨 앞에 붙인다 — 여기서는 taken_by에
    # 전원이 정확히 기록됐는지와 로그에 남는지만 확인한다.
    assert result == (
        "「광장 의뢰」 의뢰를 받았다!\n\n"
        "◊ 의뢰를 수락했습니다. 이후는 수동으로 진행됩니다. @test-admin"
    )
    assert calls == [("아도스_운반", "user1,user2,user3")]
    assert log_info is not None
    assert log_info.result == "의뢰 수주: 광장 의뢰 (user1, user2, user3)"


def test_investigation_accept_allows_different_quests_in_same_location(monkeypatch):
    """같은 장소의 서로 다른 의뢰(운반/탐사)는 서로 다른 인원이 각각 독립적으로
    수주할 수 있어야 한다 — 한 명이 하나를 수주해도 다른 의뢰는 막히지 않는다."""
    state = _make_state("user1")
    state.noncombat.investigation_overview_quest[100] = "아도스_운반"
    state.noncombat.investigation_overview_quest[101] = "아도스_탐사"
    taken_by_store: dict[str, str] = {}

    def fake_load(spreadsheet, cache=None):
        return _quest_location(), [
            _quest(quest_type="운반", taken_by=taken_by_store.get("아도스_운반", "")),
            _quest(
                quest_type="탐사",
                venue="상점가",
                taken_by=taken_by_store.get("아도스_탐사", ""),
            ),
        ]

    def fake_update(spreadsheet, quest_id, taken_by, cache=None):
        taken_by_store[quest_id] = taken_by

    monkeypatch.setattr(noncombat_module, "load_general_quest_sheet", fake_load)
    monkeypatch.setattr(noncombat_module, "update_quest_taken_by", fake_update)

    result1, _log1 = handle_investigation_accept("user1", [], state, in_reply_to_id=100)
    result2, _log2 = handle_investigation_accept("user2", [], state, in_reply_to_id=101)

    assert "의뢰를 받았다" in result1
    assert "의뢰를 받았다" in result2
    assert taken_by_store == {"아도스_운반": "user1", "아도스_탐사": "user2"}


def test_investigation_accept_rejects_already_taken_quest(monkeypatch):
    """taken_by가 이미 채워진 의뢰는 다시 [수락]할 수 없다."""
    state = _make_state("user1")
    state.noncombat.investigation_overview_quest[999] = "아도스_운반"
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [_quest(taken_by="user9")],
        ),
    )

    result, log_info = handle_investigation_accept(
        "user1", [], state, in_reply_to_id=999
    )

    assert "이미 다른 인원이 수주한 의뢰" in result


def test_investigation_accept_rejects_character_already_busy_in_same_location(
    monkeypatch,
):
    """같은 장소에서 이미 다른 의뢰를 수주한 캐릭터는 그 장소의 또 다른 의뢰를
    수주할 수 없다 (taken_by 기준 판정)."""
    state = _make_state("user1")
    state.noncombat.investigation_overview_quest[101] = "아도스_탐사"
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [
                _quest(quest_type="운반", taken_by="user1,user2"),
                _quest(quest_type="탐사", venue="상점가"),
            ],
        ),
    )

    result, log_info = handle_investigation_accept(
        "user1", [], state, in_reply_to_id=101
    )

    assert "이미 다른 의뢰를 수주한 캐릭터가 있어" in result
    assert "@user1" in result


def test_investigation_decline_reports_location_and_tags_admin(monkeypatch):
    """의뢰 개요 게시물에 [수락]도 다른 커맨드도 아닌 답글이 오면, 그 의뢰의
    location을 채운 안내 문구 + admin 태그로 응답해야 한다."""
    acct = "user1"
    state = _make_state(acct)
    state.noncombat.investigation_overview_quest[999] = "아도스_운반"
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest(venue="광장")]),
    )

    result, log_info = handle_investigation_decline(acct, state, in_reply_to_id=999)

    assert result == "의뢰는 수락하지 않고 광장 일대를 둘러보기로 했다. @test-admin"
    assert log_info is not None


def test_investigation_decline_without_known_overview_post_errors(monkeypatch):
    acct = "user1"
    state = _make_state(acct)

    result, log_info = handle_investigation_decline(acct, state, in_reply_to_id=999)

    assert "찾을 수 없습니다" in result


def test_investigation_start_uses_location_description_as_menu_intro(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(description="한적한 항구 마을이다. 어디로 가 볼까?"),
            [
                _quest(quest_type="운반", venue="광장"),
                _quest(quest_type="탐사", venue="상점가"),
                _quest(quest_type="전투", venue="항구"),
            ],
        ),
    )

    result, log_info = handle_investigation_start(acct, state)

    assert result.startswith("한적한 항구 마을이다. 어디로 가 볼까?")
    assert "▸ [광장]" in result
    assert "▸ [상점가]" in result
    assert "▸ [항구]" in result


def test_investigation_venue_choice_formats_quest_card(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [_quest(venue="광장", name="광장 의뢰", description="어쩌구")],
        ),
    )

    result, log_info = handle_investigation_venue_choice(acct, "광장", state)

    assert result == (
        "[광장](으)로 이동했다.\n"
        "\n"
        "어쩌구\n"
        "\n"
        "[일반 의뢰] 광장 의뢰\n"
        "▸ 계열: 운반 - 상시\n"
        "▸ 클리어 가능 기간: 다음 스토리 진행 전까지\n"
        "▸ 보상: 6G\n"
        "\n"
        "이 의뢰를 수락할까?\n"
        "\n"
        "◊ 의뢰를 받으려면 답글로 의뢰에 참여할 인원 전원을 멘션하면서 [수락]을 "
        "입력해 주세요. 의뢰를 받는 대신 이 장소에서 자율 탐사를 진행하려면 "
        "키워드가 없는 답글을 보내 주세요."
    )
    assert state.noncombat.investigation_acct_to_quest_id[acct] == "아도스_운반"


def test_investigation_venue_choice_free_explore_tags_admin(monkeypatch):
    """메뉴에 없는 장소(자율 탐사 포함)를 고르면 GM이 후속 진행을 알 수
    있도록 메시지 끝에 admin 계정을 태그해야 한다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest()]),
    )

    result, log_info = handle_investigation_venue_choice(
        acct, "그 외의 장소를 찾아본다.", state
    )

    assert result == (
        "다른 곳에 가보기로 했다. 자유롭게 일대를 돌아다니며 "
        "정보를 수집할 수 있다. @test-admin"
    )


def test_daily_quest_roll_reports_success_and_clears_mid_when_save_succeeds(
    monkeypatch,
):
    acct = "user1"
    state = _make_state(acct)
    saved_calls = []
    monkeypatch.setattr(
        noncombat_module,
        "update_character_gold_and_quest_date",
        lambda *a, **k: saved_calls.append(a),
    )

    result, log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "사례로 1G를 획득했다. (소지금: 11G)" in result
    assert acct not in state.noncombat.daily_quest_mid
    # 캐릭터 데이터는 매 커맨드마다 새로 읽으므로, 로컬 캐시가 아니라
    # 스프레드시트에 실제로 반영된 값(gold=11)을 검증한다.
    assert saved_calls == [(None, "동료", 11, saved_calls[0][3])]
    assert log_info is not None
    assert log_info.error_trace is None


def test_daily_quest_roll_appends_ledger_row_on_success(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_gold_and_quest_date", lambda *a, **k: None
    )
    ledger_calls = []
    monkeypatch.setattr(
        noncombat_module,
        "append_ledger_row",
        lambda *a, **k: ledger_calls.append((a, k)),
    )

    handle_daily_quest_roll(acct, "육체", state)

    assert len(ledger_calls) == 1
    args, kwargs = ledger_calls[0]
    assert args == (
        None,
        date.today().isoformat(),
        "동료",
        "일일 의뢰",
        1,
        11,
    )
    assert kwargs == {"cache": state.sheet_cache}


def test_daily_quest_roll_skips_ledger_row_when_save_fails(monkeypatch):
    acct = "user1"
    state = _make_state(acct)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(noncombat_module, "update_character_gold_and_quest_date", _boom)
    ledger_calls = []
    monkeypatch.setattr(
        noncombat_module,
        "append_ledger_row",
        lambda *a, **k: ledger_calls.append((a, k)),
    )

    handle_daily_quest_roll(acct, "육체", state)

    assert ledger_calls == []


def test_daily_quest_roll_tolerates_ledger_append_failure(monkeypatch):
    """가계부 기록이 실패해도 의뢰 완수 자체(골드 지급, 응답)는 정상 진행돼야 한다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_gold_and_quest_date", lambda *a, **k: None
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(noncombat_module, "append_ledger_row", _boom)

    result, _log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "사례로 1G를 획득했다. (소지금: 11G)" in result
    assert acct not in state.noncombat.daily_quest_mid


def test_finalize_daily_quest_mid_persists_status_id_and_updates_in_memory_state(
    monkeypatch,
):
    acct = "user1"
    state = _make_state(acct)
    saved_calls = []
    monkeypatch.setattr(
        noncombat_module,
        "update_character_daily_quest_status_id",
        lambda *a, **k: saved_calls.append(a),
    )

    finalize_daily_quest_mid(acct, 999, state)

    assert state.noncombat.daily_quest_mid[acct].bot_reply_post_id == 999
    assert saved_calls == [(None, "동료", "999")]


def test_finalize_daily_quest_mid_tolerates_persist_failure(monkeypatch):
    """스프레드시트 저장이 실패해도 인메모리 mid_state는 정상 갱신되고,
    예외가 호출측까지 전파되면 안 된다 — 재기동 복원만 안 될 뿐, 이 프로세스가
    떠 있는 동안은 정상 진행돼야 한다."""
    acct = "user1"
    state = _make_state(acct)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(
        noncombat_module, "update_character_daily_quest_status_id", _boom
    )

    finalize_daily_quest_mid(acct, 999, state)

    assert state.noncombat.daily_quest_mid[acct].bot_reply_post_id == 999


def test_restore_daily_quest_mid_state_reads_status_id_column():
    """bot_reply_post_id는 문자열 그대로 복원되어야 한다 — mastodon.py의
    게시물 ID는 실제로 str 서브클래스(MaybeSnowflakeIdType)라, int로
    캐스팅하면 실제 알림에서 오는 in_reply_to_id와 더 이상 같지 않게 되어
    매칭에 항상 실패한다(재기동 복원이 조용히 무력화되는 회귀 케이스)."""
    acct = "user1"
    state = BotState(
        char_dict={},
        name_dict={},
        noncombat_char_dict={
            acct: NoncombatCharacterDataFromSpreadsheet(
                name="동료", daily_quest_status_id="555"
            ),
            "user2": NoncombatCharacterDataFromSpreadsheet(name="다른캐릭터"),
        },
        spreadsheet=None,
        field_spreadsheet=None,
    )

    restored = _restore_daily_quest_mid_state(state)

    assert restored == 1
    assert state.noncombat.daily_quest_mid[acct].bot_reply_post_id == "555"
    assert "user2" not in state.noncombat.daily_quest_mid
    # 실제 알림에서 in_reply_to_id로 오는 값(문자열)과 그대로 매칭돼야 한다.
    assert "555" in state.noncombat.get_daily_quest_post_ids()


def test_daily_quest_roll_reports_failure_and_keeps_mid_when_save_fails(monkeypatch):
    acct = "user1"
    state = _make_state(acct)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(noncombat_module, "update_character_gold_and_quest_date", _boom)

    result, log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "사례로 1G를 획득했다" not in result
    assert "저장" in result
    assert acct in state.noncombat.daily_quest_mid
    assert state.noncombat_char_dict[acct].gold == 10
    assert log_info is not None
    assert log_info.error_trace is not None


def test_daily_quest_roll_judgment_always_prefixed_with_success_type(monkeypatch):
    """message가 시트에 있어도 봇이 항상 '{success_type}! '을 앞에 붙여야 한다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_gold_and_quest_date", lambda *a, **k: None
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_daily_quest_result_messages",
        lambda spreadsheet, cache=None: [
            DailyQuestResultMessageData(
                success_type=DailyQuestSuccessType.GREAT_SUCCESS,
                message="완벽한 솜씨로 해결했다.",
            )
        ],
    )
    monkeypatch.setattr(random, "randint", lambda a, b: 6)  # 6+2 → 「8」 → 대성공

    result, log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "대성공! 완벽한 솜씨로 해결했다." in result


def test_daily_quest_roll_judgment_prefix_alone_when_no_message_row(monkeypatch):
    """해당 success_type의 메시지 행이 없으면 접두어만 출력된다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_gold_and_quest_date", lambda *a, **k: None
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_daily_quest_result_messages",
        lambda spreadsheet, cache=None: [],
    )
    monkeypatch.setattr(random, "randint", lambda a, b: 6)  # 6+2 → 「8」 → 대성공

    result, log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "대성공!\n" in result


def test_daily_quest_roll_reply_labels_dice_part_with_1d6(monkeypatch):
    """일일 의뢰 판정도 [판정/스탯]과 동일하게 "◊ 판정: {스탯값}[{스탯명}] +
    {주사위}[1d6] → 「합계」" 형식으로 표시해야 한다."""
    acct = "user1"
    state = _make_state(acct)  # stat_physical=2
    monkeypatch.setattr(
        noncombat_module, "update_character_gold_and_quest_date", lambda *a, **k: None
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_daily_quest_result_messages",
        lambda spreadsheet, cache=None: [],
    )
    monkeypatch.setattr(random, "randint", lambda a, b: 6)

    result, _log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "◊ 판정: 2[육체] + 6[1d6] → 「8」" in result


def test_daily_quest_roll_adds_blank_line_before_completion_message(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_gold_and_quest_date", lambda *a, **k: None
    )

    result, log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "\n\n의뢰를 완수했다. 사례로 1G를 획득했다. (소지금: 11G)" in result


def test_daily_quest_start_formats_client_name_and_description(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_daily_quest_pools",
        lambda spreadsheet, cache=None: _daily_quest_pools(
            client_categories=("길 잃은",),
            client_names=("어린아이로부터",),
            quest_contents=("부모를 찾아달라고 의뢰했다",),
        ),
    )

    result, log_info = handle_daily_quest_start(acct, state)

    assert result.startswith(
        "길 잃은 어린아이로부터 부모를 찾아달라고 의뢰했다. 어떻게 할까?"
    )
    assert log_info is not None


def test_daily_quest_start_does_not_add_or_alter_particle(monkeypatch):
    """조사(로부터/으로부터) 선택은 코드가 하지 않는다 — client_name에
    입력된 조사를 그대로 이어붙일 뿐이다. 종성 유무에 따라 둘 다 그대로
    통과하는지 확인한다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_daily_quest_pools",
        lambda spreadsheet, cache=None: _daily_quest_pools(
            client_categories=("마을",),
            client_names=("촌장으로부터",),
            quest_contents=("세금 장부를 정리해달라고 의뢰했다",),
        ),
    )

    result, log_info = handle_daily_quest_start(acct, state)

    assert result.startswith(
        "마을 촌장으로부터 세금 장부를 정리해달라고 의뢰했다. 어떻게 할까?"
    )


def test_daily_quest_start_combines_pools_independently(monkeypatch):
    """client_category/client_name/quest_content 세 풀은 행 단위로 대응하지
    않는 독립적인 테이블이므로, 풀 크기가 서로 달라도(2×1×3) 조합이 가능해야
    한다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(
        noncombat_module,
        "load_daily_quest_pools",
        lambda spreadsheet, cache=None: _daily_quest_pools(
            client_categories=("장터", "마을"),
            client_names=("아주머니로부터",),
            quest_contents=(
                "무거운 짐을 옮겨달라고 의뢰했다",
                "약초를 채집해달라고 의뢰했다",
                "순찰해달라고 의뢰했다",
            ),
        ),
    )

    result, log_info = handle_daily_quest_start(acct, state)

    assert result.startswith(
        "장터 아주머니로부터 무거운 짐을 옮겨달라고 의뢰했다. 어떻게 할까?"
    )


def test_daily_quest_start_unavailable_when_any_pool_empty(monkeypatch):
    """id/row 단위 검증이 없으므로, 세 풀 중 하나라도 active인 값이 없으면
    조합 자체가 불가능해 의뢰를 제공하지 않는다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_daily_quest_pools",
        lambda spreadsheet, cache=None: _daily_quest_pools(
            client_categories=(),
        ),
    )

    result, log_info = handle_daily_quest_start(acct, state)

    assert "받을 수 있는 의뢰가 없습니다" in result


def test_failed_venue_choice_clears_stale_quest_mapping(monkeypatch):
    """유효한 장소를 골라 의뢰를 확인한 뒤, 같은 메뉴에 다시 무효한 장소를
    입력하면 이전에 저장된 quest_id가 남아 있으면 안 된다 (엉뚱한 의뢰의
    수주로 이어지는 것을 방지)."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [_quest(venue="장소A", name="퀘스트1", description="설명")],
        ),
    )

    # 1. 유효한 장소를 선택 → quest_id가 저장된다
    handle_investigation_venue_choice(acct, "장소A", state)
    assert state.noncombat.investigation_acct_to_quest_id.get(acct) == "아도스_운반"

    # 2. 같은 메뉴에 존재하지 않는 장소를 다시 입력 → 실패 응답이지만
    #    이전에 저장된 quest_id는 지워져야 한다
    result, log_info = handle_investigation_venue_choice(
        acct, "존재하지 않는 장소", state
    )

    assert "등록되지 않은 장소입니다" in result
    assert acct not in state.noncombat.investigation_acct_to_quest_id
    assert log_info is not None


# ---------------------------------------------------------------------------
# 비전투 아이템 사용/양도
# ---------------------------------------------------------------------------


def test_parse_use_item_args_defaults_to_self_and_one():
    assert parse_use_item_args("[사용/포션]") == ("포션", None, 1)


def test_parse_use_item_args_with_target_and_count_any_order():
    assert parse_use_item_args("[사용/포션/동료/2개]") == ("포션", "동료", 2)
    assert parse_use_item_args("[사용/포션/2개/동료]") == ("포션", "동료", 2)


def test_parse_transfer_item_args_requires_target():
    assert parse_transfer_item_args("[양도/포션/동료]") == ("포션", "동료", 1)
    assert parse_transfer_item_args("[양도/포션/동료/3개]") == ("포션", "동료", 3)


@pytest.fixture
def potion_item() -> ItemData:
    return ItemData(
        id="포션",
        target_rule="SkillTargetRuleSelf",
        cost=0,
        attack_range=0,
        effect=SkillEffectHeal(
            ValueSourceType.FIXED, 20, ValueType.INTEGER, None, None
        ),
        item_type=ItemType.CONSUMABLE,
    )


@pytest.fixture
def bomb_item() -> ItemData:
    """비전투에서 지원하지 않는 대미지 아이템."""
    return ItemData(
        id="폭탄",
        target_rule="SkillTargetRuleNamed",
        cost=0,
        attack_range=1,
        effect=SkillEffectDamage(
            ValueSourceType.FIXED, 30, ValueType.INTEGER, None, None
        ),
        item_type=ItemType.CONSUMABLE,
    )


@pytest.fixture
def key_item() -> ItemData:
    """전투/비전투 효과 없이 소지 자체가 목적인 스토리 키 아이템."""
    return ItemData(
        id="수상한 양탄자",
        target_rule="SkillTargetRuleSelf",
        cost=0,
        attack_range=0,
        effect=None,
        item_type=ItemType.CONSUMABLE,
    )


def _make_state_with_name_dict(acct: str, char_name: str, curr_hp: int) -> BotState:
    state = _make_state(acct)
    state.noncombat_char_dict[acct] = NoncombatCharacterDataFromSpreadsheet(
        name=char_name, gold=0, daily_quest_date=""
    )
    state.name_dict = {char_name: get_test_preset(char_name, initial_hp=curr_hp)}
    return state


def test_use_item_heals_self_and_consumes_inventory(monkeypatch, potion_item):
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    inventory = Inventory({("동료", "포션"): 1})
    recorded_hp: dict = {}

    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"포션": potion_item},
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )
    monkeypatch.setattr(
        noncombat_module,
        "update_character_curr_hp",
        lambda spreadsheet, name, hp, cache=None: recorded_hp.__setitem__(name, hp),
    )

    reply, log_info = handle_use_item(acct, "포션", None, 1, state)

    assert "회복" in reply
    assert recorded_hp == {"동료": 70}
    assert inventory.get_count("동료", "포션") == 0
    assert log_info is not None
    assert log_info.error_trace is None


def test_use_item_rejects_unsupported_effect_type(monkeypatch, bomb_item):
    """item_type="소모품"(비전투에서도 사용 가능)이라도 회복이 아닌 효과(대미지 등)는
    비전투에서 지원하지 않는다."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"폭탄": bomb_item},
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_inventory",
        lambda spreadsheet, cache=None: Inventory({("동료", "폭탄"): 1}),
    )

    reply, log_info = handle_use_item(acct, "폭탄", None, 1, state)

    assert "지원하지 않는 효과" in reply
    assert log_info is not None


def test_use_item_rejects_key_item_without_effect(monkeypatch, key_item):
    """effect가 없는(None) 키 아이템도 대미지 아이템과 동일하게 "지원하지
    않는 효과"로 거부돼야 한다 — isinstance(None, SkillEffectHeal)이
    False이므로 크래시 없이 자연스럽게 같은 분기를 탄다."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"수상한 양탄자": key_item},
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_inventory",
        lambda spreadsheet, cache=None: Inventory({("동료", "수상한 양탄자"): 1}),
    )

    reply, log_info = handle_use_item(acct, "수상한 양탄자", None, 1, state)

    assert "지원하지 않는 효과" in reply
    assert log_info is not None


def test_use_item_rejects_when_item_type_not_usable_outside_battle(
    monkeypatch, potion_item
):
    from dataclasses import replace

    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    battle_only_potion = replace(potion_item, item_type=ItemType.BATTLE_CONSUMABLE)
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"포션": battle_only_potion},
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_inventory",
        lambda spreadsheet, cache=None: Inventory({("동료", "포션"): 1}),
    )

    reply, log_info = handle_use_item(acct, "포션", None, 1, state)

    assert reply == "◊ 사용할 수 없는 아이템입니다."
    assert log_info is not None


def test_use_item_rejects_when_insufficient_inventory(monkeypatch, potion_item):
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"포션": potion_item},
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_inventory",
        lambda spreadsheet, cache=None: Inventory({}),
    )

    reply, log_info = handle_use_item(acct, "포션", None, 1, state)

    assert "수가 부족" in reply


def test_use_item_rejects_target_other_than_self_for_noncombat_only_item(monkeypatch):
    """item_type="비전투 소모품"은 자신 외의 대상을 지정하면 거부돼야 한다
    (target_rule이 비어 있어도 이 검증은 item_type만으로 동작한다)."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    state.name_dict["동료2"] = get_test_preset("동료2")
    potion = ItemData(
        id="수상한 물약",
        target_rule="",
        cost=0,
        attack_range=0,
        effect=None,
        item_type=ItemType.NONCOMBAT_CONSUMABLE,
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"수상한 물약": potion},
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_inventory",
        lambda spreadsheet, cache=None: Inventory({("동료", "수상한 물약"): 1}),
    )

    reply, log_info = handle_use_item(acct, "수상한 물약", "동료2", 1, state)

    assert reply == "◊ 자신에게만 사용할 수 있는 아이템입니다."


def test_use_item_reports_unimplemented_noncombat_only_item(monkeypatch):
    """"수상한 물약" 외의 비전투 소모품은 전용 로직이 아직 없으므로 안내
    메시지를 낸다(인벤토리는 이미 소비된다)."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    charm = ItemData(
        id="정체불명의 씨앗",
        target_rule="SkillTargetRuleSelf",
        cost=0,
        attack_range=0,
        effect=None,
        item_type=ItemType.NONCOMBAT_CONSUMABLE,
    )
    inventory = Inventory({("동료", "정체불명의 씨앗"): 1})
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"정체불명의 씨앗": charm},
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )

    reply, log_info = handle_use_item(acct, "정체불명의 씨앗", None, 1, state)

    assert "아직 구현되지 않았습니다" in reply
    assert inventory.get_count("동료", "정체불명의 씨앗") == 0


def test_use_mysterious_potion_reports_random_effect(monkeypatch):
    """"수상한 물약" 사용 시 "수상한 효과" 시트의 텍스트 중 하나를 그대로 출력한다."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    potion = ItemData(
        id="수상한 물약",
        target_rule="SkillTargetRuleSelf",
        cost=0,
        attack_range=0,
        effect=None,
        item_type=ItemType.NONCOMBAT_CONSUMABLE,
    )
    inventory = Inventory({("동료", "수상한 물약"): 1})
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"수상한 물약": potion},
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_mysterious_potion_effects",
        lambda spreadsheet, cache=None: ["배가 조금 아프다."],
    )

    reply, log_info = handle_use_item(acct, "수상한 물약", None, 1, state)

    assert reply == (
        "수상한 물약을 마셨다. ……어라? 배가 조금 아프다.\n"
        "\n"
        "◊ 효과는 자정 혹은 스토리 진행 전까지 지속됩니다. 기존에 진행 중이던 대화에는 반영되지 않습니다."
    )
    assert inventory.get_count("동료", "수상한 물약") == 0
    assert log_info is not None
    assert log_info.result == "배가 조금 아프다."


def test_use_mysterious_potion_heal_effect_updates_hp(monkeypatch):
    """"체력이 N 회복된다." 효과가 뽑히면 캐릭터 스프레드시트에 반영하고
    답글 뒤에 "(회복 후 체력/최대 체력)"을 덧붙인다."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    potion = ItemData(
        id="수상한 물약",
        target_rule="SkillTargetRuleSelf",
        cost=0,
        attack_range=0,
        effect=None,
        item_type=ItemType.NONCOMBAT_CONSUMABLE,
    )
    inventory = Inventory({("동료", "수상한 물약"): 1})
    recorded_hp: dict = {}
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"수상한 물약": potion},
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_mysterious_potion_effects",
        lambda spreadsheet, cache=None: ["체력이 100 회복된다."],
    )
    monkeypatch.setattr(
        noncombat_module,
        "update_character_curr_hp",
        lambda spreadsheet, name, hp, cache=None: recorded_hp.__setitem__(name, hp),
    )

    reply, log_info = handle_use_item(acct, "수상한 물약", None, 1, state)

    max_hp = state.name_dict["동료"].max_hp
    assert reply == (
        f"수상한 물약을 마셨다. ……어라? 체력이 100 회복된다. ({max_hp}/{max_hp})\n"
        "\n"
        "◊ 효과는 자정 혹은 스토리 진행 전까지 지속됩니다. 기존에 진행 중이던 대화에는 반영되지 않습니다."
    )
    assert recorded_hp == {"동료": max_hp}


def test_transfer_item_moves_between_characters(monkeypatch, potion_item):
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    state.name_dict["동료2"] = get_test_preset("동료2")
    inventory = Inventory({("동료", "포션"): 3})

    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"포션": potion_item},
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )

    reply, log_info = handle_transfer_item(acct, "포션", "동료2", 2, state)

    assert "양도했습니다" in reply
    assert inventory.get_count("동료", "포션") == 1
    assert inventory.get_count("동료2", "포션") == 2


def test_transfer_item_requires_target(monkeypatch, potion_item):
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)

    reply, log_info = handle_transfer_item(acct, "포션", None, 1, state)

    assert "대상을 지정" in reply


def test_bag_lists_gold_and_items_with_cost_range_and_usable_suffix(
    monkeypatch, potion_item
):
    acct = "user1"
    state = _make_state(acct)  # gold=10
    battle_only_item = ItemData(
        id="화염병",
        target_rule="SkillTargetRuleNamed",
        cost=2,
        attack_range=3,
        effect=SkillEffectDamage(
            ValueSourceType.FIXED, 15, ValueType.INTEGER, None, None
        ),
        description="적에게 화염 피해를 입힌다.",
        item_type=ItemType.BATTLE_CONSUMABLE,
    )
    inventory = Inventory({("동료", "포션"): 2, ("동료", "화염병"): 1})
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {
            "포션": potion_item,
            "화염병": battle_only_item,
        },
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )

    reply, log_info = handle_bag(acct, state)

    assert reply == (
        "◊ 동료의 소지품\n"
        "\n"
        "▹ 소지금: 10G\n"
        f"▹ 포션×2: (자신 · 코스트 {potion_item.cost} · 사거리 {potion_item.attack_range}) "
        f"{potion_item.description} 비전투 상황에서도 사용 가능.\n"
        "▹ 화염병×1: (코스트 2 · 사거리 3) 적에게 화염 피해를 입힌다."
    )
    assert log_info is not None


def test_bag_omits_cost_range_for_types_without_battle_slot(monkeypatch):
    """"기타"/"비전투 소모품"/"부적"은 코스트·사거리가 항상 0이므로
    [가방]에서 코스트/사거리 표기를 생략한다."""
    acct = "user1"
    state = _make_state(acct)
    key_item = ItemData(
        id="수상한 양탄자",
        target_rule="",
        cost=0,
        attack_range=0,
        effect=None,
        description="용도 불명의 양탄자.",
        item_type=ItemType.ETC,
    )
    potion = ItemData(
        id="수상한 물약",
        target_rule="SkillTargetRuleSelf",
        cost=0,
        attack_range=0,
        effect=None,
        description="마셔 봐야 아는 물약.",
        item_type=ItemType.NONCOMBAT_CONSUMABLE,
    )
    charm = ItemData(
        id="행운의 부적",
        target_rule="",
        cost=0,
        attack_range=0,
        effect=None,
        description="지니고 있으면 운이 좋아진다.",
        item_type=ItemType.CHARM,
    )
    inventory = Inventory(
        {
            ("동료", "수상한 양탄자"): 1,
            ("동료", "수상한 물약"): 1,
            ("동료", "행운의 부적"): 1,
        }
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {
            "수상한 양탄자": key_item,
            "수상한 물약": potion,
            "행운의 부적": charm,
        },
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )

    reply, log_info = handle_bag(acct, state)

    assert "코스트" not in reply
    assert "사거리" not in reply
    assert "▹ 수상한 양탄자×1: 용도 불명의 양탄자." in reply
    assert "▹ 수상한 물약×1: 마셔 봐야 아는 물약." in reply
    assert "비전투 전용" not in reply
    assert "▹ 행운의 부적×1: 부적. 지니고 있으면 운이 좋아진다." in reply


def test_bag_shows_target_label_for_consumable_item(monkeypatch):
    """"소모품"은 target_rule에 따라 "(대상라벨 · 코스트 N · 사거리 M)"
    형태로 코스트/사거리와 한 덩어리로 붙인다."""
    acct = "user1"
    state = _make_state(acct)
    self_potion = ItemData(
        id="자가 물약",
        target_rule="SkillTargetRuleSelf",
        cost=1,
        attack_range=0,
        effect=SkillEffectHeal(
            ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
        ),
        description="체력을 회복한다.",
        item_type=ItemType.CONSUMABLE,
    )
    named_potion = ItemData(
        id="지정 물약",
        target_rule="SkillTargetRuleNamed",
        cost=1,
        attack_range=1,
        effect=SkillEffectHeal(
            ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
        ),
        description="체력을 회복한다.",
        item_type=ItemType.CONSUMABLE,
    )
    column_potion = ItemData(
        id="살포 물약",
        target_rule="SkillTargetRuleAllyColumn",
        cost=1,
        attack_range=1,
        effect=SkillEffectHeal(
            ValueSourceType.FIXED, 10, ValueType.INTEGER, None, None
        ),
        description="체력을 회복한다.",
        item_type=ItemType.CONSUMABLE,
    )
    inventory = Inventory(
        {
            ("동료", "자가 물약"): 1,
            ("동료", "지정 물약"): 1,
            ("동료", "살포 물약"): 1,
        }
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {
            "자가 물약": self_potion,
            "지정 물약": named_potion,
            "살포 물약": column_potion,
        },
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )

    reply, log_info = handle_bag(acct, state)

    assert "(자신 · 코스트 1 · 사거리 0) 체력을 회복한다." in reply
    assert "(개체/1 · 코스트 1 · 사거리 1) 체력을 회복한다." in reply
    assert "(열/1 · 코스트 1 · 사거리 1) 체력을 회복한다." in reply


def test_bag_shows_placeholder_when_item_info_missing(monkeypatch):
    """인벤토리에는 있지만 '아이템' 시트에서 찾을 수 없는 항목(삭제된
    아이템 등)은 코스트/사거리 없이 안내 문구만 보여준다."""
    acct = "user1"
    state = _make_state(acct)
    inventory = Inventory({("동료", "단종된 아이템"): 1})
    monkeypatch.setattr(
        noncombat_module, "load_item_data", lambda spreadsheet, cache=None: {}
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )

    reply, log_info = handle_bag(acct, state)

    assert "▹ 단종된 아이템×1: (아이템 정보를 찾을 수 없습니다)" in reply


def test_bag_shows_gold_only_when_no_items(monkeypatch):
    acct = "user1"
    state = _make_state(acct)  # gold=10
    monkeypatch.setattr(
        noncombat_module, "load_item_data", lambda spreadsheet, cache=None: {}
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_inventory",
        lambda spreadsheet, cache=None: Inventory({}),
    )

    reply, log_info = handle_bag(acct, state)

    assert reply == "◊ 동료의 소지품\n\n▹ 소지금: 10G"


def test_bag_rejects_unregistered_character(monkeypatch):
    state = _make_state("user1")

    reply, log_info = handle_bag("unregistered_user", state)

    assert "등록된 캐릭터를 찾을 수 없습니다" in reply
    assert log_info is None


def test_handle_1d100_reply_format(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(random, "randint", lambda a, b: 42)

    reply, log_info = handle_1d100(acct, state)

    assert reply == "◊ 1d100 → 「42」"
    assert log_info is not None
    assert log_info.command_text == "[1D100]"
    assert log_info.dice_roll == "42"
    assert log_info.error_trace is None


def test_handle_1d100_rejects_unregistered_character():
    state = _make_state("user1")

    reply, log_info = handle_1d100("unregistered_user", state)

    assert "등록된 캐릭터를 찾을 수 없습니다" in reply
    assert log_info is None
