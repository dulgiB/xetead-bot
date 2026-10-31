import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")
os.environ.setdefault("WORLD_MASTODON_ID", "test-world")

import random  # noqa: E402
import time  # noqa: E402
from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from battle.objects.define import ItemType, ValueSourceType, ValueType  # noqa: E402
from battle.objects.item.models import ItemData  # noqa: E402
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectHeal  # noqa: E402
from bot import commands as _  # noqa: E402, F401
from bot.commands import noncombat as noncombat_module  # noqa: E402
from bot.commands.noncombat import (  # noqa: E402
    finalize_daily_quest_mid,
    finalize_investigation_menu_post,
    get_cached_item_names,
    handle_dice,
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
    parse_bare_item_command,
    parse_dice_command,
    parse_roll_command,
    parse_roll_target,
    parse_transfer_item_args,
)
from bot.main import BotState  # noqa: E402
from bot.main import _restore_daily_quest_mid_state  # noqa: E402
from bot.noncombat_state import DailyQuestMidState, InvestigationSession  # noqa: E402
from bot.thread_index import normalize_post_id  # noqa: E402
from mastodon.types_base import MaybeSnowflakeIdType  # noqa: E402
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
        log_spreadsheet=None,
    )
    state.noncombat.daily_quest_mid[acct] = DailyQuestMidState(bot_reply_post_id=123)
    return state


@pytest.fixture(autouse=True)
def _stub_investigation_persistence(monkeypatch):
    """upsert_investigation_session()은 실제 스프레드시트 쓰기라, 이 파일의
    모든 테스트에서 기본적으로 무력화한다(state.spreadsheet=None이라
    그대로 두면 크래시한다). 실제 호출 여부/인자를 검증하고 싶은 테스트는
    그 안에서 다시 monkeypatch.setattr로 덮어쓰면 된다."""
    monkeypatch.setattr(
        noncombat_module, "upsert_investigation_session", lambda *a, **k: None
    )


def _investigation_session(
    acct: str = "user1",
    menu_post_id: int = 100,
    overview_post_id: int | None = None,
    quest_id: str | None = None,
) -> InvestigationSession:
    return InvestigationSession(
        field_id=str(menu_post_id),
        accts=[acct],
        menu_post_id=menu_post_id,
        overview_post_id=overview_post_id,
        quest_id=quest_id,
    )


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


# ── [판정+/스탯] 키워드 보정 ───────────────────────────────────────────────────


def _keyword_state(
    acct: str = "user1",
    *,
    revival_count: int = 1,
    keyword_date: str = "",
    curr_hp: int = 100,
) -> BotState:
    state = _make_state(acct)
    state.noncombat_char_dict[acct] = NoncombatCharacterDataFromSpreadsheet(
        name="동료",
        stat_physical=2,
        gold=10,
        daily_quest_date="",
        curr_hp=curr_hp,
        max_hp=100,
        revival_count=revival_count,
        keyword_date=keyword_date,
    )
    return state


@pytest.fixture
def _stub_keyword_sheet_writes(monkeypatch):
    """키워드 보정 대가 반영은 실제 스프레드시트 쓰기라 무력화하고, 호출된
    인자만 기록해 검증할 수 있게 한다."""
    calls: dict[str, object] = {}
    monkeypatch.setattr(
        noncombat_module,
        "update_character_curr_hp",
        lambda _sheet, name, hp, cache=None: calls.update(hp=(name, hp)),
    )
    monkeypatch.setattr(
        noncombat_module,
        "update_character_keyword_date",
        lambda _sheet, name, today, cache=None: calls.update(keyword=(name, today)),
    )
    return calls


def test_parse_roll_command_detects_keyword_suffix():
    """[판정+/스탯]은 스탯명과 키워드 보정 플래그로 갈라 파싱되어야 한다."""
    assert parse_roll_command("[판정+/육체]") == ("육체", True)
    assert parse_roll_command("[판정/육체]") == ("육체", False)
    assert parse_roll_command("사담") is None


def test_handle_roll_keyword_auto_succeeds_and_costs_hp(
    monkeypatch, _stub_keyword_sheet_writes
):
    """키워드 보정 판정은 주사위를 굴리지 않고 자동 성공하며 체력 20을 소모한다."""
    acct = "user1"
    state = _keyword_state(acct)

    def _fail_roll(a, b):
        raise AssertionError("키워드 보정 판정은 주사위를 굴리지 않아야 한다")

    monkeypatch.setattr(random, "randint", _fail_roll)

    result, log_info = handle_roll(acct, "육체", state, keyword_boost=True)

    assert result.splitlines()[0] == "◊ 판정: 육체 — 키워드 보정 사용"
    assert _stub_keyword_sheet_writes["hp"] == ("동료", 80)
    assert _stub_keyword_sheet_writes["keyword"] == ("동료", date.today().isoformat())
    assert log_info is not None
    assert log_info.command_text == "[판정+/육체]"
    assert log_info.dice_roll == ""
    assert log_info.result == "「자동 성공」"


def test_handle_roll_keyword_updates_in_memory_character(_stub_keyword_sheet_writes):
    """같은 멘션 안에서 재조회해도 소모가 반영되도록 인메모리 값도 갱신한다."""
    acct = "user1"
    state = _keyword_state(acct)

    handle_roll(acct, "육체", state, keyword_boost=True)

    updated = state.noncombat_char_dict[acct]
    assert updated.curr_hp == 80
    assert updated.keyword_date == date.today().isoformat()


def test_handle_roll_keyword_requires_revival(_stub_keyword_sheet_writes):
    """부활 경험이 없으면 판정 자체를 하지 않는다."""
    state = _keyword_state("user1", revival_count=0)

    result, _log_info = handle_roll("user1", "육체", state, keyword_boost=True)

    assert "부활 횟수" in result
    assert "「" not in result
    assert not _stub_keyword_sheet_writes


def test_handle_roll_keyword_blocked_when_used_today(_stub_keyword_sheet_writes):
    """오늘 이미 썼으면 거부한다."""
    state = _keyword_state("user1", keyword_date=date.today().isoformat())

    result, _log_info = handle_roll("user1", "육체", state, keyword_boost=True)

    assert "오늘 이미 사용" in result
    assert not _stub_keyword_sheet_writes


def test_handle_roll_keyword_allowed_when_used_on_another_day(
    _stub_keyword_sheet_writes,
):
    """어제 썼다면 오늘은 다시 쓸 수 있다 — 별도 리셋 절차가 필요 없다."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    state = _keyword_state("user1", keyword_date=yesterday)

    result, _log_info = handle_roll("user1", "육체", state, keyword_boost=True)

    assert "키워드 보정" in result
    assert _stub_keyword_sheet_writes["keyword"] == ("동료", date.today().isoformat())


def test_handle_roll_keyword_blocked_when_hp_too_low(_stub_keyword_sheet_writes):
    """체력이 소모량 이하면 거부한다."""
    state = _keyword_state("user1", curr_hp=20)

    result, _log_info = handle_roll("user1", "육체", state, keyword_boost=True)

    assert "체력" in result
    assert not _stub_keyword_sheet_writes


def test_handle_roll_without_keyword_touches_nothing(_stub_keyword_sheet_writes):
    """일반 판정은 체력/사용 기록을 건드리지 않는다."""
    state = _keyword_state("user1")

    handle_roll("user1", "육체", state)

    assert not _stub_keyword_sheet_writes


# ── world/admin이 요구한 판정 목표치 ────────────────────────────────────────────────


def test_parse_roll_target_reads_subject_thresholds_and_penalty():
    target = parse_roll_target(
        "어떻게 할까? **[판정: 최소 1인] [지식 7/기술 6, 실패 시 패널티]**"
    )

    assert target is not None
    assert target.thresholds == {"지식": 7, "기술": 6}
    assert target.subject == "최소 1인"
    assert target.penalty


def test_parse_roll_target_accepts_bare_tag_without_subject():
    target = parse_roll_target("**[판정] [지식 8]**")

    assert target is not None
    assert target.thresholds == {"지식": 8}
    assert target.subject == ""
    assert not target.penalty


def test_parse_roll_target_accepts_value_without_space():
    target = parse_roll_target("[판정: 최소 1인] [지식8/ 「대상」 지식 4]")

    assert target is not None
    assert target.thresholds == {"지식": 8}
    assert target.character_thresholds == (("대상", "지식", 4),)


def test_parse_roll_target_ignores_player_roll_command():
    assert parse_roll_target("[판정/지식]") is None


@pytest.mark.parametrize(("dice", "verdict"), [(5, "성공"), (4, "실패")])
def test_handle_roll_reports_verdict_at_threshold(monkeypatch, dice, verdict):
    """목표치와 같으면 성공이다."""
    state = _make_state("user1")  # stat_physical=2
    monkeypatch.setattr(random, "randint", lambda a, b: dice)
    target = parse_roll_target("[판정: 최소 1인] [육체 7/지식 4]")

    result, log_info = handle_roll("user1", "육체", state, target=target)

    assert result.splitlines()[1] == f"↳ 목표치: 육체 7 — **{verdict}**"
    assert log_info is not None
    assert verdict in log_info.result


def test_handle_roll_marks_penalty_only_on_failure(monkeypatch):
    state = _make_state("user1")
    target = parse_roll_target("[판정: 최소 1인] [육체 7, 실패 시 패널티]")

    monkeypatch.setattr(random, "randint", lambda a, b: 1)
    failed, _log_info = handle_roll("user1", "육체", state, target=target)
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    passed, _log_info = handle_roll("user1", "육체", state, target=target)

    assert "↳ 목표치: 육체 7 — **실패** (패널티 적용)" in failed
    assert "↳ 목표치: 육체 7 — **성공**" in passed
    assert "패널티" not in passed


def test_handle_roll_without_matching_stat_is_plain_roll():
    state = _make_state("user1")
    target = parse_roll_target("[판정: 최소 1인] [지식 7]")

    result, _log_info = handle_roll("user1", "육체", state, target=target)

    assert "목표치" not in result


def test_handle_roll_for_other_named_character_is_plain_roll():
    """대상으로 지목되지 않은 캐릭터의 판정은 일반 판정으로 취급한다."""
    state = _make_state("user1")
    state.noncombat_char_dict["user2"] = NoncombatCharacterDataFromSpreadsheet(
        name="대상 캐릭터", gold=0, daily_quest_date=""
    )
    target = parse_roll_target("[판정: 대상 캐릭터] [육체 7]")

    result, _log_info = handle_roll("user1", "육체", state, target=target)

    assert "목표치" not in result


def test_handle_roll_for_one_of_several_named_characters_reports_verdict():
    state = _make_state("user1")  # name="동료"
    target = parse_roll_target("[판정: 다른 캐릭터, 동료] [육체 7]")

    result, _log_info = handle_roll("user1", "육체", state, target=target)

    assert "↳ 목표치: 육체 7" in result


def test_handle_roll_for_named_character_reports_verdict():
    state = _make_state("user1")  # name="동료"
    target = parse_roll_target("[판정: 동료] [육체 7]")

    result, _log_info = handle_roll("user1", "육체", state, target=target)

    assert "↳ 목표치: 육체 7" in result


def test_parse_roll_target_reads_character_specific_threshold():
    target = parse_roll_target("[판정: 최소 1인] [지식 7/「대상」 지식 5]")

    assert target is not None
    assert target.thresholds == {"지식": 7}
    assert target.character_thresholds == (("대상", "지식", 5),)


@pytest.mark.parametrize(("name", "threshold"), [("동료", "5"), ("다른 캐릭터", "7")])
def test_handle_roll_uses_character_specific_threshold(name, threshold):
    """「이름」이 붙은 목표치는 그 캐릭터에게만 기본 목표치를 대신한다."""
    state = _make_state("user1")
    state.noncombat_char_dict["user1"] = NoncombatCharacterDataFromSpreadsheet(
        name=name, gold=0, daily_quest_date=""
    )
    target = parse_roll_target("[판정: 최소 1인] [육체 7/「동료」 육체 5]")

    result, _log_info = handle_roll("user1", "육체", state, target=target)

    assert f"↳ 목표치: 육체 {threshold}" in result


def test_handle_roll_keyword_succeeds_regardless_of_threshold(
    _stub_keyword_sheet_writes,
):
    """키워드 보정은 목표치와 무관하게 성공하고, 목표치 줄은 체력 소모 줄 앞에 온다."""
    state = _keyword_state("user1")
    target = parse_roll_target("[판정: 최소 1인] [육체 99, 실패 시 패널티]")

    result, log_info = handle_roll(
        "user1", "육체", state, keyword_boost=True, target=target
    )

    lines = result.splitlines()
    assert lines[0] == "◊ 판정: 육체 — 키워드 보정 사용"
    assert lines[1] == "↳ 목표치: 육체 99 — **성공**"
    assert lines[2].startswith("↳ 키워드 보정 사용")
    assert log_info is not None
    assert log_info.result == "「자동 성공」 목표치 99 성공"


# ── 특수 판정 (스탯 자리에 스탯이 아닌 텍스트) ───────────────────────────────────


def test_parse_roll_target_reads_special_check_names():
    """스탯이 아닌 텍스트도 판정 이름으로 읽고, 스탯 이름은 그대로 일반 판정이다(테스트)."""
    target = parse_roll_target(
        "[판정] [판정 이름 6/지식 5/「대상_1」 판정_1 4, 실패 시 패널티 1]"
    )

    assert target is not None
    assert target.thresholds == {"판정 이름": 6, "지식": 5}
    assert target.character_thresholds == (("대상_1", "판정_1", 4),)
    assert target.penalty


@pytest.mark.parametrize(("dice", "verdict"), [(6, "성공"), (5, "실패")])
def test_handle_roll_special_check_uses_bare_dice(monkeypatch, dice, verdict):
    """특수 판정은 스탯 보정 없이 1d6 그대로 목표치와 견준다(테스트)."""
    state = _make_state("user1")  # stat_physical=2
    monkeypatch.setattr(random, "randint", lambda a, b: dice)
    target = parse_roll_target("[판정] [「동료」 판정_1 6]")

    result, log_info = handle_roll("user1", "판정_1", state, target=target)

    assert result.splitlines() == [
        f"◊ 판정: {dice}[1d6] → 「{dice}」",
        f"↳ 목표치: 판정_1 6 — **{verdict}**",
    ]
    assert log_info is not None
    assert log_info.dice_roll == str(dice)
    assert log_info.result == f"「{dice}」 목표치 6 {verdict}"


def test_handle_roll_special_check_ignores_spacing(monkeypatch):
    """판정 이름은 공백 차이와 무관하게 받는다(테스트)."""
    state = _make_state("user1")
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    target = parse_roll_target("[판정: 최소 1인] [오래된 판정 5]")

    result, _log_info = handle_roll("user1", "오래된판정", state, target=target)

    assert "↳ 목표치: 오래된 판정 5 — **성공**" in result


def test_handle_roll_special_check_for_other_character_is_rejected():
    """다른 캐릭터 전용 특수 판정은 굴릴 수 없다 — 일반 판정으로 바꿀 스탯이 없다(테스트)."""
    state = _make_state("user1")  # name="동료"
    state.noncombat_char_dict["user2"] = NoncombatCharacterDataFromSpreadsheet(
        name="대상 캐릭터", gold=0, daily_quest_date=""
    )
    target = parse_roll_target("[판정] [「대상 캐릭터」 판정_1 6]")

    result, _log_info = handle_roll("user1", "판정_1", state, target=target)

    assert result.startswith("◊ 알 수 없는 스탯입니다.")


@pytest.mark.parametrize("typed", ["「대상_1」 판정_1", "대상_1 판정_1"])
def test_handle_roll_special_check_with_unregistered_name_is_part_of_name(
    monkeypatch, typed
):
    """「이름」이 등록된 캐릭터가 아니면 판정 이름의 일부로 보고 누구나 굴린다(테스트)."""
    state = _make_state("user1")
    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    target = parse_roll_target("[판정] [「대상_1」 판정_1 4]")

    result, _log_info = handle_roll("user1", typed, state, target=target)

    assert "↳ 목표치: 「대상_1」 판정_1 4 — **성공**" in result


@pytest.mark.parametrize(
    "post", [None, "[판정: 최소 1인] [지식 7]", "[판정] [판정_2 6]"]
)
def test_handle_roll_special_check_without_matching_target_is_rejected(post):
    """진행 게시물이 그 이름을 요구하지 않았으면 오타일 수 있으므로 거부한다(테스트)."""
    state = _make_state("user1")
    target = parse_roll_target(post) if post else None

    result, log_info = handle_roll("user1", "판정_1", state, target=target)

    assert result.startswith("◊ 알 수 없는 스탯입니다.")
    assert log_info is not None


def test_handle_roll_special_check_keyword_auto_succeeds(_stub_keyword_sheet_writes):
    """특수 판정에도 키워드 보정을 쓸 수 있고, 판정 이름은 게시물 표기를 따른다(테스트)."""
    state = _keyword_state("user1")
    target = parse_roll_target("[판정] [판정 이름 99]")

    result, log_info = handle_roll(
        "user1", "판정이름", state, keyword_boost=True, target=target
    )

    lines = result.splitlines()
    assert lines[0] == "◊ 판정: 판정 이름 — 키워드 보정 사용"
    assert lines[1] == "↳ 목표치: 판정 이름 99 — **성공**"
    assert lines[2].startswith("↳ 키워드 보정 사용")
    assert log_info is not None
    assert log_info.result == "「자동 성공」 목표치 99 성공"


def _alias_state(aliases: tuple[str, ...]) -> BotState:
    """user1("동료")에게 별명을 붙이고, 다른 캐릭터 user2("다른 캐릭터")를 둔다."""
    from dataclasses import replace

    state = _make_state("user1")
    state.noncombat_char_dict["user2"] = NoncombatCharacterDataFromSpreadsheet(
        name="다른 캐릭터", gold=0, daily_quest_date=""
    )
    state.name_dict = {
        "동료": replace(get_test_preset("동료"), name_aliases=aliases),
    }
    return state


@pytest.mark.parametrize(
    ("acct", "expected"), [("user1", "↳ 목표치: 육체 5"), ("user2", "↳ 목표치: 육체 7")]
)
def test_handle_roll_character_threshold_accepts_alias(acct, expected):
    """「별명」으로 지정한 캐릭터별 목표치는 그 캐릭터에게만 적용된다(테스트)."""
    state = _alias_state(("별명_1",))
    target = parse_roll_target("[판정: 최소 1인] [육체 7/「별명_1」 육체 5]")

    result, _log_info = handle_roll(acct, "육체", state, target=target)

    assert expected in result


def test_handle_roll_special_check_accepts_alias(monkeypatch):
    """특수 판정의 「별명」도 그 캐릭터 전용 목표치로 읽는다(테스트)."""
    state = _alias_state(("별명_1",))
    monkeypatch.setattr(random, "randint", lambda a, b: 6)
    target = parse_roll_target("[판정] [「별명_1」 판정_1 6]")

    own, _log_info = handle_roll("user1", "판정_1", state, target=target)
    other, _log_info = handle_roll("user2", "판정_1", state, target=target)

    assert "↳ 목표치: 판정_1 6 — **성공**" in own
    assert other.startswith("◊ 알 수 없는 스탯입니다.")


def test_handle_roll_subject_accepts_alias():
    """대상 칸에 별명을 쓰면 그 캐릭터만 목표치를 받는다(테스트)."""
    state = _alias_state(("별명_1",))
    target = parse_roll_target("[판정: 별명_1] [육체 7]")

    own, _log_info = handle_roll("user1", "육체", state, target=target)
    other, _log_info = handle_roll("user2", "육체", state, target=target)

    assert "↳ 목표치: 육체 7" in own
    assert "목표치" not in other


def _quest_location(
    location_id: str = "항구 마을",
    active: bool = True,
    description_quest: str = "항구 마을이다.",
) -> QuestLocationData:
    return QuestLocationData(
        id=location_id, active=active, description_quest=description_quest
    )


def _quest(
    location_id: str = "항구 마을",
    quest_type: str = "운반",
    venue: str = "광장",
    name: str = "광장 의뢰",
    description_quest: str = "어쩌구",
    description_normal: str = "이미 처리된 의뢰다.",
    reward: str = "6G",
    available_until: str = "다음 스토리 진행 전까지",
    taken_by: str = "",
    special_for: str = "",
    special_description: str = "",
) -> QuestData:
    return QuestData(
        id=f"{location_id}_{quest_type}",
        active=True,
        location=venue,
        name=name,
        description_quest=description_quest,
        description_normal=description_normal,
        type=quest_type,
        reward=reward,
        available_until=available_until,
        taken_by=taken_by,
        special_for=special_for,
        special_description=special_description,
    )


def test_handle_investigation_accept_returns_log_info(monkeypatch):
    """[수락]도 마찬가지로 NoncombatLogInfo를 반환해 로그에 남아야 한다."""
    state = _make_state("user1")
    session = _investigation_session(acct="user1", quest_id="항구 마을_운반")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest()]),
    )
    monkeypatch.setattr(noncombat_module, "update_quest_taken_by", lambda *a, **k: None)

    result, log_info = handle_investigation_accept(session, ["user1"], state)

    assert "의뢰를 받았다" in result
    assert log_info is not None
    assert log_info.command_text == "[수락]"
    assert session.ended is True


def test_investigation_accept_writes_taken_by_and_registers_mentions(monkeypatch):
    """[수락] 답글에 멘션된 인원 전원(+ 발신자)이 참여자로 등록되고, '일반 의뢰'
    시트의 taken_by에 쉼표로 이어붙여 기록되어야 한다."""
    state = _make_state("user1")
    session = _investigation_session(acct="user1", quest_id="항구 마을_운반")
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
        session, ["user1", "user2", "user3"], state
    )

    # 참여자 전원 멘션은 handle_investigation_accept 자체가 아니라 main.py의
    # _reply(mention_accts=...)가 게시물 맨 앞에 붙인다 — 여기서는 taken_by에
    # 전원이 정확히 기록됐는지와 로그에 남는지만 확인한다.
    assert result == (
        "「광장 의뢰」 의뢰를 받았다!\n\n"
        "◊ 의뢰를 수락했습니다. 이후는 수동으로 진행됩니다. @test-world"
    )
    assert calls == [("항구 마을_운반", "user1,user2,user3")]
    assert log_info is not None
    assert log_info.result == "의뢰 수주: 광장 의뢰 (user1, user2, user3)"


def test_investigation_accept_allows_different_quests_in_same_location(monkeypatch):
    """같은 장소의 서로 다른 의뢰(운반/탐사)는 서로 다른 인원이 각각 독립적으로
    수주할 수 있어야 한다 — 한 명이 하나를 수주해도 다른 의뢰는 막히지 않는다."""
    state = _make_state("user1")
    session1 = _investigation_session(
        acct="user1", menu_post_id=100, quest_id="항구 마을_운반"
    )
    session2 = _investigation_session(
        acct="user2", menu_post_id=101, quest_id="항구 마을_탐사"
    )
    taken_by_store: dict[str, str] = {}

    def fake_load(spreadsheet, cache=None):
        return _quest_location(), [
            _quest(
                quest_type="운반", taken_by=taken_by_store.get("항구 마을_운반", "")
            ),
            _quest(
                quest_type="탐사",
                venue="상점가",
                taken_by=taken_by_store.get("항구 마을_탐사", ""),
            ),
        ]

    def fake_update(spreadsheet, quest_id, taken_by, cache=None):
        taken_by_store[quest_id] = taken_by

    monkeypatch.setattr(noncombat_module, "load_general_quest_sheet", fake_load)
    monkeypatch.setattr(noncombat_module, "update_quest_taken_by", fake_update)

    result1, _log1 = handle_investigation_accept(session1, ["user1"], state)
    result2, _log2 = handle_investigation_accept(session2, ["user2"], state)

    assert "의뢰를 받았다" in result1
    assert "의뢰를 받았다" in result2
    assert taken_by_store == {"항구 마을_운반": "user1", "항구 마을_탐사": "user2"}


def test_investigation_accept_rejects_already_taken_quest(monkeypatch):
    """taken_by가 이미 채워진 의뢰는 다시 [수락]할 수 없다."""
    state = _make_state("user1")
    session = _investigation_session(acct="user1", quest_id="항구 마을_운반")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [_quest(taken_by="user9")],
        ),
    )

    result, log_info = handle_investigation_accept(session, ["user1"], state)

    assert "이미 다른 인원이 수주한 의뢰" in result


def test_investigation_accept_rejects_character_already_busy_in_same_location(
    monkeypatch,
):
    """같은 장소에서 이미 다른 의뢰를 수주한 캐릭터는 그 장소의 또 다른 의뢰를
    수주할 수 없다 (taken_by 기준 판정)."""
    state = _make_state("user1")
    session = _investigation_session(
        acct="user1", menu_post_id=101, quest_id="항구 마을_탐사"
    )
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

    result, log_info = handle_investigation_accept(session, ["user1"], state)

    assert "이미 다른 의뢰를 수주한 캐릭터가 있어" in result
    assert "@user1" in result


def test_investigation_decline_reports_location_and_tags_admin(monkeypatch):
    """의뢰 개요 게시물에 [수락]도 다른 커맨드도 아닌 답글이 오면, 그 의뢰의
    location을 채운 안내 문구 + admin 태그로 응답해야 한다."""
    state = _make_state("user1")
    session = _investigation_session(acct="user1", quest_id="항구 마을_운반")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest(venue="광장")]),
    )

    result, log_info = handle_investigation_decline(session, state)

    assert result == "의뢰는 수락하지 않고 광장 일대를 둘러보기로 했다. @test-world"
    assert log_info is not None
    assert session.ended is True


def test_investigation_decline_without_known_overview_post_errors():
    state = _make_state("user1")
    session = _investigation_session(acct="user1", quest_id=None)

    result, log_info = handle_investigation_decline(session, state)

    assert "찾을 수 없습니다" in result


def test_investigation_start_uses_location_description_as_menu_intro(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(description_quest="한적한 항구 마을이다. 어디로 가 볼까?"),
            [
                _quest(quest_type="운반", venue="광장"),
                _quest(quest_type="탐사", venue="상점가"),
                _quest(quest_type="전투", venue="항구"),
            ],
        ),
    )

    result, log_info = handle_investigation_start([acct], state)

    assert result.startswith("한적한 항구 마을이다. 어디로 가 볼까?")
    assert "▸ [광장]" in result
    assert "▸ [상점가]" in result
    assert "▸ [자율 탐사]" in result
    assert "▸ [항구]" in result


def test_investigation_start_separates_intro_from_choices(monkeypatch):
    state = _make_state("user1")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(description_quest="항구 마을이다."),
            [_quest(venue="광장")],
        ),
    )

    result, _log_info = handle_investigation_start(["user1"], state)

    assert result == "항구 마을이다.\n\n▸ [광장]\n▸ [자율 탐사]"


def test_investigation_start_offers_free_explore_without_active_quests(monkeypatch):
    state = _make_state("user1")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(description_quest="항구 마을이다."),
            [],
        ),
    )

    result, _log_info = handle_investigation_start(["user1"], state)

    assert result == "항구 마을이다.\n\n▸ [자율 탐사]"


def test_investigation_start_unavailable_without_active_location(monkeypatch):
    state = _make_state("user1")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (None, []),
    )

    result, _log_info = handle_investigation_start(["user1"], state)

    assert result == "◊ 현재 상시조사를 진행할 수 없는 구간입니다."


def _special_quest_sheet(monkeypatch):
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(description_quest="항구 마을이다."),
            [
                _quest(quest_type="운반", venue="광장"),
                _quest(
                    quest_type="특수",
                    venue="등대",
                    name="등대 의뢰",
                    special_for="user1, user2@other.example",
                ),
                _quest(quest_type="탐사", venue="상점가"),
            ],
        ),
    )


def test_investigation_start_shows_special_choice_to_listed_character(monkeypatch):
    """특수 선택지는 일반 선택지와 [자율 탐사] 사이에 "[장소]※"로 나온다."""
    state = _make_state("user1")
    _special_quest_sheet(monkeypatch)

    result, log_info = handle_investigation_start(["user1"], state)

    assert result == (
        "항구 마을이다.\n\n▸ [광장]\n▸ [상점가]\n▸ [등대]※\n▸ [자율 탐사]"
    )
    assert log_info is not None
    assert log_info.result == "메뉴 제공: 광장, 상점가, 등대※, 자율 탐사"


def _special_description_sheet(monkeypatch):
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(description_quest="항구 마을이다."),
            [
                _quest(quest_type="운반", venue="광장"),
                _quest(
                    quest_type="특수1",
                    venue="등대",
                    special_for="user1",
                    special_description="등대에 불이 켜져 있다.",
                ),
                _quest(
                    quest_type="특수2",
                    venue="동굴",
                    special_for="user2",
                    special_description="동굴에서 소리가 난다. ",
                ),
                _quest(
                    quest_type="일반",
                    venue="상점가",
                    special_description="일반 선택지에는 붙지 않는다.",
                ),
            ],
        ),
    )


def test_investigation_start_appends_special_description_to_intro(monkeypatch):
    """보이는 특수 선택지의 문장만 소개 뒤에 공백 하나로 이어 붙는다."""
    state = _make_state("user1")
    _special_description_sheet(monkeypatch)

    result, _log_info = handle_investigation_start(["user1"], state)

    assert result == (
        "항구 마을이다. 등대에 불이 켜져 있다.\n\n"
        "▸ [광장]\n▸ [상점가]\n▸ [등대]※\n▸ [자율 탐사]"
    )


def test_investigation_start_joins_multiple_special_descriptions(monkeypatch):
    state = _make_state("user1")
    _special_description_sheet(monkeypatch)

    result, _log_info = handle_investigation_start(["user1", "user2"], state)

    assert result.startswith(
        "항구 마을이다. 등대에 불이 켜져 있다. 동굴에서 소리가 난다.\n\n"
    )


def test_investigation_start_omits_special_description_when_hidden(monkeypatch):
    state = _make_state("user3")
    _special_description_sheet(monkeypatch)

    result, _log_info = handle_investigation_start(["user3"], state)

    assert result.startswith("항구 마을이다.\n\n")


def test_investigation_start_matches_remote_acct_in_special_list(monkeypatch):
    state = _make_state("user2@other.example")
    _special_quest_sheet(monkeypatch)

    result, _log_info = handle_investigation_start(["user2@other.example"], state)

    assert "▸ [등대]※" in result


def test_investigation_start_hides_special_choice_from_others(monkeypatch):
    state = _make_state("user3")
    _special_quest_sheet(monkeypatch)

    result, _log_info = handle_investigation_start(["user3"], state)

    assert result == "항구 마을이다.\n\n▸ [광장]\n▸ [상점가]\n▸ [자율 탐사]"


def test_investigation_venue_choice_accepts_special_choice(monkeypatch):
    """특수 선택지를 고른 뒤의 개요는 일반 선택지와 같다. 표식을 괄호 안에
    넣어 답해도 받는다."""
    state = _make_state("user1")
    session = _investigation_session(acct="user1")
    _special_quest_sheet(monkeypatch)

    result, _log_info = handle_investigation_venue_choice(session, "등대※", state)

    assert result.startswith("[등대](으)로 이동했다.")
    assert "**[일반 의뢰] 등대 의뢰**" in result
    assert session.quest_id == "항구 마을_특수"


def test_investigation_start_shows_special_choice_if_any_participant_listed(
    monkeypatch,
):
    """함께 멘션된 참여자 중 한 명이라도 목록에 있으면 특수 선택지가 보인다."""
    state = _make_state("user3")
    _special_quest_sheet(monkeypatch)

    result, _log_info = handle_investigation_start(["user3", "user1"], state)

    assert "▸ [등대]※" in result


def test_investigation_venue_choice_allows_special_choice_for_any_participant(
    monkeypatch,
):
    state = _make_state("user3")
    session = InvestigationSession(
        field_id="100", accts=["user3", "user1"], menu_post_id=100
    )
    _special_quest_sheet(monkeypatch)

    handle_investigation_venue_choice(session, "등대", state)

    assert session.quest_id == "항구 마을_특수"


def test_investigation_venue_choice_rejects_special_choice_for_others(monkeypatch):
    """메뉴에 보이지 않은 특수 선택지는 이름으로 입력해도 고를 수 없다."""
    state = _make_state("user3")
    session = InvestigationSession(
        field_id="100", accts=["user3", "user4"], menu_post_id=100
    )
    _special_quest_sheet(monkeypatch)

    result, _log_info = handle_investigation_venue_choice(session, "등대", state)

    assert result == "◊ 등록되지 않은 장소입니다."
    assert session.quest_id is None


def test_quest_lists_tolerate_space_after_comma():
    """직접 입력한 값에 쉼표 뒤 공백이 있어도 같은 목록으로 읽는다."""
    quest = _quest(taken_by="user1, user2", special_for="user3,  user4 ")

    assert quest.taken_by_list() == ["user1", "user2"]
    assert quest.special_for_list() == ["user3", "user4"]


def test_investigation_venue_choice_explore_only_tags_world(monkeypatch):
    """description_quest 없이 description_normal만 있는 선택지는 의뢰 개요 없이
    description_normal과 함께 바로 world를 태그하고 세션을 끝낸다."""
    state = _make_state("user1")
    session = _investigation_session(acct="user1")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [
                _quest(
                    quest_type="특수",
                    venue="골목",
                    name="",
                    description_quest="",
                    description_normal="누군가 골목을 살피고 있다.",
                    special_for="user1",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        noncombat_module, "upsert_investigation_session", lambda *a, **k: None
    )

    result, log_info = handle_investigation_venue_choice(session, "골목", state)

    assert result == (
        "[골목](으)로 이동했다.\n\n"
        f"누군가 골목을 살피고 있다. @{noncombat_module.WORLD_MASTODON_ID}"
    )
    assert session.ended is True
    assert session.quest_id is None
    assert log_info is not None
    assert log_info.result == "자율 탐사 전용 장소: 골목"


def test_investigation_venue_choice_formats_quest_card(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    session = _investigation_session(acct=acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [_quest(venue="광장", name="광장 의뢰", description_quest="어쩌구")],
        ),
    )

    result, log_info = handle_investigation_venue_choice(session, "광장", state)

    assert result == (
        "[광장](으)로 이동했다.\n"
        "\n"
        "어쩌구\n"
        "\n"
        "**[일반 의뢰] 광장 의뢰**\n"
        "▸ 계열: 운반\n"
        "▸ 클리어 가능 기간: 다음 스토리 진행 전까지\n"
        "▸ 보상: 6G\n"
        "\n"
        "이 의뢰를 수락할까?\n"
        "\n"
        "◊ 의뢰를 받으려면 답글로 [수락]을 입력해 주세요. 그 시점까지 이 "
        "스레드에 참여한 인원 전원이 함께 의뢰를 받습니다. 의뢰를 받는 대신 이 "
        "장소에서 자율 탐사를 진행하려면 키워드가 없는 답글을 보내 주세요."
    )
    assert session.quest_id == "항구 마을_운반"


def test_investigation_venue_choice_hides_accept_prompt_when_taken(monkeypatch):
    """이미 수주된 의뢰는 description_quest 대신 description_normal을
    노출하고, 수락 유도 문구 없이 자율 탐사/이동 안내만 보여줘야 한다."""
    acct = "user1"
    state = _make_state(acct)
    session = _investigation_session(acct=acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [
                _quest(
                    venue="광장",
                    name="광장 의뢰",
                    description_quest="어쩌구",
                    description_normal="이미 처리된 일이다.",
                    taken_by="user9",
                )
            ],
        ),
    )

    result, log_info = handle_investigation_venue_choice(session, "광장", state)

    assert result == (
        "[광장](으)로 이동했다.\n"
        "\n"
        "이미 처리된 일이다.\n"
        "\n"
        "◊ 이 장소의 의뢰는 이미 누군가에 의해 수주되었습니다. 커맨드가 없는 "
        "답글을 보내 자율 탐사를 시작하거나, 커맨드를 입력해 다른 장소로 "
        "이동할 수 있습니다."
    )
    assert "어쩌구" not in result
    assert "이 의뢰를 수락할까?" not in result
    assert "[일반 의뢰]" not in result
    assert session.quest_id == "항구 마을_운반"


def test_investigation_venue_choice_free_explore_tags_admin(monkeypatch):
    """메뉴에 없는 장소(자율 탐사 포함)를 고르면 GM이 후속 진행을 알 수
    있도록 메시지 끝에 admin 계정을 태그해야 한다."""
    acct = "user1"
    state = _make_state(acct)
    session = _investigation_session(acct=acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest()]),
    )

    result, log_info = handle_investigation_venue_choice(session, "자율 탐사", state)

    assert result == (
        "다른 곳에 가보기로 했다. 자유롭게 일대를 돌아다니며 "
        "정보를 수집할 수 있다. @test-world"
    )
    assert session.ended is True


def test_daily_quest_roll_reports_success_and_clears_mid_when_save_succeeds(
    monkeypatch,
):
    acct = "user1"
    state = _make_state(acct)
    saved_calls = []
    monkeypatch.setattr(
        noncombat_module,
        "update_character_quest_date",
        lambda *a, **k: saved_calls.append(a),
    )

    result, log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "사례로 1G를 획득했다. (소지금: 11G)" in result
    assert acct not in state.noncombat.daily_quest_mid
    # gold는 더 이상 캐릭터 시트에 쓰지 않는다 — daily_quest_date만 갱신한다.
    assert saved_calls == [(None, "동료", saved_calls[0][2])]
    assert log_info is not None
    assert log_info.error_trace is None


def test_daily_quest_roll_appends_ledger_row_on_success(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
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
    )
    assert kwargs == {"cache": state.sheet_cache}


def test_daily_quest_roll_reports_gold_refetched_after_ledger_append(monkeypatch):
    """gold는 "가계부" 내역을 근거로 한 스프레드시트 수식이므로, 가계부에
    행을 추가한 직후에는 char_data.gold + 1이 아니라 그 수식이 계산한
    실제 값을 다시 읽어 표시해야 한다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
    )
    monkeypatch.setattr(noncombat_module, "append_ledger_row", lambda *a, **k: None)
    monkeypatch.setattr(noncombat_module, "get_character_gold", lambda *a, **k: 42)

    result, _log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "사례로 1G를 획득했다. (소지금: 42G)" in result


def test_daily_quest_roll_falls_back_to_local_gold_when_refetch_fails(monkeypatch):
    """가계부 기록 자체는 성공했지만 gold 재조회가 실패하면, 답글이 아예
    깨지는 대신 char_data.gold + 1 예상치로 대체 표시해야 한다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
    )
    monkeypatch.setattr(noncombat_module, "append_ledger_row", lambda *a, **k: None)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(noncombat_module, "get_character_gold", _boom)

    result, _log_info = handle_daily_quest_roll(acct, "육체", state)

    assert "사례로 1G를 획득했다. (소지금: 11G)" in result
    assert acct not in state.noncombat.daily_quest_mid


def test_daily_quest_roll_skips_gold_refetch_when_ledger_append_fails(monkeypatch):
    """가계부 기록 자체가 실패하면 방금 실패한 기록을 전제로 gold를 다시
    읽어봐야 의미가 없으므로 재조회를 시도하지 않아야 한다."""
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(noncombat_module, "append_ledger_row", _boom)
    refetch_calls = []
    monkeypatch.setattr(
        noncombat_module,
        "get_character_gold",
        lambda *a, **k: refetch_calls.append((a, k)) or 999,
    )

    handle_daily_quest_roll(acct, "육체", state)

    assert refetch_calls == []


def test_daily_quest_roll_skips_ledger_row_when_save_fails(monkeypatch):
    acct = "user1"
    state = _make_state(acct)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(noncombat_module, "update_character_quest_date", _boom)
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
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
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
    """시트에서 읽은 bot_reply_post_id는 알림 id와 같은 모양
    (normalize_post_id)으로 복원되어야 한다 — 모양이 다르면 같은 게시물인데도
    실제 알림의 in_reply_to_id(mastodon.py의 str 서브클래스)와 매칭에 실패한다
    (재기동 복원이 조용히 무력화되는 회귀 케이스)."""
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
        log_spreadsheet=None,
    )

    restored = _restore_daily_quest_mid_state(state)

    assert restored == 1
    assert state.noncombat.daily_quest_mid[acct].bot_reply_post_id == 555
    assert "user2" not in state.noncombat.daily_quest_mid
    # 실제 알림에서 in_reply_to_id로 오는 값(문자열 계열)도 맞춘 뒤 매칭돼야 한다.
    assert (
        normalize_post_id(MaybeSnowflakeIdType("555"))
        in state.noncombat.get_daily_quest_post_ids()
    )


def test_daily_quest_roll_reports_failure_and_keeps_mid_when_save_fails(monkeypatch):
    acct = "user1"
    state = _make_state(acct)

    def _boom(*args, **kwargs):
        raise RuntimeError("시트 접근 실패")

    monkeypatch.setattr(noncombat_module, "update_character_quest_date", _boom)

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
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
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
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
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
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
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
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
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


def test_investigation_venue_choice_free_explore_without_quests(monkeypatch):
    state = _make_state("user1")
    session = _investigation_session(acct="user1")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), []),
    )

    result, _log_info = handle_investigation_venue_choice(session, "자율 탐사", state)

    assert result.endswith("@test-world")
    assert session.ended is True


def test_failed_venue_choice_clears_stale_quest_mapping(monkeypatch):
    """유효한 장소를 골라 의뢰를 확인한 뒤, 같은 메뉴에 다시 무효한 장소를
    입력하면 세션에 남아 있던 quest_id가 지워져야 한다 — 그래야 이 실패
    답글이 뒤이어 finalize_investigation_overview_post에서 옛 의뢰의
    개요인 것처럼 등록되어 엉뚱한 의뢰가 수주되는 것을 막는다."""
    acct = "user1"
    state = _make_state(acct)
    session = _investigation_session(acct=acct)
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (
            _quest_location(),
            [_quest(venue="장소A", name="퀘스트1", description_quest="설명")],
        ),
    )

    # 1. 유효한 장소를 선택 → quest_id가 저장된다
    handle_investigation_venue_choice(session, "장소A", state)
    assert session.quest_id == "항구 마을_운반"

    # 2. 같은 메뉴에 존재하지 않는 장소를 다시 입력 → 실패 응답이지만
    #    이전에 저장된 quest_id는 지워져야 한다
    result, log_info = handle_investigation_venue_choice(
        session, "존재하지 않는 장소", state
    )

    assert "등록되지 않은 장소입니다" in result
    assert session.quest_id is None
    assert log_info is not None


# ---------------------------------------------------------------------------
# 비전투 아이템 사용/양도
# ---------------------------------------------------------------------------


def _state_with_item_name_cache(names: set[str]) -> BotState:
    state = _make_state("user1")
    state.item_name_cache = frozenset(names)
    state.item_name_cache_loaded_at = time.monotonic()
    return state


def test_parse_bare_item_command_defaults_to_self_and_one():
    state = _state_with_item_name_cache({"포션"})
    assert parse_bare_item_command("[포션]", state) == ("포션", None, 1)


def test_parse_bare_item_command_with_target_and_count_any_order():
    state = _state_with_item_name_cache({"포션"})
    assert parse_bare_item_command("[포션/동료/2개]", state) == ("포션", "동료", 2)
    assert parse_bare_item_command("[포션/2개/동료]", state) == ("포션", "동료", 2)


def test_parse_bare_item_command_ignores_unregistered_name():
    """등록된 아이템명과 일치하지 않는 대괄호 텍스트는 아이템 사용으로
    인식하지 않고 조용히 무시해야 한다(다른 커맨드나 사담과의 충돌 방지)."""
    state = _state_with_item_name_cache({"포션"})
    assert parse_bare_item_command("[등록되지 않은 이름]", state) is None


def test_parse_bare_item_command_matches_whitespace_variant():
    """등록된 아이템명과 공백만 다르게 입력해도 인식해야 한다(등록된 표기로
    치환된 이름을 반환)."""
    state = _state_with_item_name_cache({"소형 회복 물약"})
    assert parse_bare_item_command("[소형회복물약/동료]", state) == (
        "소형 회복 물약",
        "동료",
        1,
    )


def test_get_cached_item_names_reuses_cache_within_ttl(monkeypatch):
    state = _make_state("user1")
    calls = []
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: calls.append(1) or {"포션": object()},
    )

    first = get_cached_item_names(state)
    second = get_cached_item_names(state)

    assert first == frozenset({"포션"})
    assert second == first
    assert len(calls) == 1


def test_get_cached_item_names_refetches_after_ttl_expires(monkeypatch):
    state = _make_state("user1")
    calls = []
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: calls.append(1) or {"포션": object()},
    )

    get_cached_item_names(state)
    state.item_name_cache_loaded_at -= noncombat_module._ITEM_NAME_CACHE_TTL_SEC + 1
    get_cached_item_names(state)

    assert len(calls) == 2


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
        id="키 아이템",
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

    assert reply == "◊ 포션 1개를 사용했습니다.\n\n▹ 동료 | +20 → 70/100"
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
        lambda spreadsheet, cache=None: {"키 아이템": key_item},
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_inventory",
        lambda spreadsheet, cache=None: Inventory({("동료", "키 아이템"): 1}),
    )

    reply, log_info = handle_use_item(acct, "키 아이템", None, 1, state)

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


def test_use_item_rejects_unimplemented_noncombat_only_item_without_consuming(
    monkeypatch,
):
    """ "수상한 물약" 외의 비전투 소모품은 전용 로직이 아직 없다 — 플레이어
    입장에서는 등록되지 않은 아이템과 다를 바 없어야 하므로 같은 메시지로
    거절하고, 처리할 방법이 없는 아이템을 소비해 버리지 않는다."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    charm = ItemData(
        id="비전투 소모품 아이템",
        target_rule="SkillTargetRuleSelf",
        cost=0,
        attack_range=0,
        effect=None,
        item_type=ItemType.NONCOMBAT_CONSUMABLE,
    )
    inventory = Inventory({("동료", "비전투 소모품 아이템"): 1})
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"비전투 소모품 아이템": charm},
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )

    reply, log_info = handle_use_item(acct, "비전투 소모품 아이템", None, 1, state)

    assert reply == "◊ 등록되지 않은 아이템입니다."
    assert inventory.get_count("동료", "비전투 소모품 아이템") == 1


def test_use_mysterious_potion_reports_random_effect(monkeypatch):
    """ "수상한 물약" 사용 시 "수상한 효과" 시트의 텍스트 중 하나를 그대로 출력한다."""
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
    """ "체력이 N 회복된다." 효과가 뽑히면 캐릭터 스프레드시트에 반영하고
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


def test_use_item_defaults_to_one_when_count_omitted(monkeypatch, potion_item):
    """개수를 생략하면 1개 사용을 기본으로 한다."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    inventory = Inventory({("동료", "포션"): 2})
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {"포션": potion_item},
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )
    monkeypatch.setattr(
        noncombat_module, "update_character_curr_hp", lambda *a, **k: None
    )

    reply, log_info = handle_use_item(acct, "포션", None, 1, state)

    assert "▹ 동료 | +20 → 70/100" in reply  # potion_item: 고정값 20
    assert inventory.get_count("동료", "포션") == 1


def test_use_item_scales_heal_by_count(monkeypatch, potion_item):
    """[소형 회복 물약/2]처럼 개수를 지정하면 회복량과 소비량이 그만큼
    늘어나야 한다."""
    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    inventory = Inventory({("동료", "포션"): 3})
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

    reply, log_info = handle_use_item(acct, "포션", None, 2, state)

    assert reply == "◊ 포션 2개를 사용했습니다.\n\n▹ 동료 | +40 → 90/100"  # 20 × 2개
    assert inventory.get_count("동료", "포션") == 1
    assert recorded_hp == {"동료": 90}


def test_use_mysterious_potion_multiple_count_joins_effects(monkeypatch):
    """[수상한 물약/2]처럼 개수를 지정하면 그만큼 효과를 뽑아 " 그리고…… "로
    이어붙여 출력한다."""
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
    inventory = Inventory({("동료", "수상한 물약"): 2})
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
        lambda spreadsheet, cache=None: ["배가 조금 아프다.", "기분이 좋아진다."],
    )
    monkeypatch.setattr(
        random,
        "choices",
        lambda population, k=1: ["배가 조금 아프다.", "기분이 좋아진다."][:k],
    )

    reply, log_info = handle_use_item(acct, "수상한 물약", None, 2, state)

    assert reply == (
        "수상한 물약을 마셨다. ……어라? 배가 조금 아프다. 그리고…… 기분이 좋아진다.\n"
        "\n"
        "◊ 효과는 자정 혹은 스토리 진행 전까지 지속됩니다. 기존에 진행 중이던 대화에는 반영되지 않습니다."
    )
    assert inventory.get_count("동료", "수상한 물약") == 0
    assert log_info is not None
    assert log_info.result == "배가 조금 아프다. 그리고…… 기분이 좋아진다."


def test_use_mysterious_potion_multiple_count_sums_heal_effects(monkeypatch):
    """여러 개를 사용해 체력 회복 효과가 여러 번 뽑히면 회복량을 합산해
    한 번만 반영해야 한다."""
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
    inventory = Inventory({("동료", "수상한 물약"): 2})
    recorded_hp: dict = {}
    update_calls: list = []
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
        lambda spreadsheet, cache=None: ["체력이 10 회복된다.", "체력이 20 회복된다."],
    )
    monkeypatch.setattr(
        random,
        "choices",
        lambda population, k=1: ["체력이 10 회복된다.", "체력이 20 회복된다."][:k],
    )

    def fake_update(spreadsheet, name, hp, cache=None):
        update_calls.append((name, hp))
        recorded_hp[name] = hp

    monkeypatch.setattr(noncombat_module, "update_character_curr_hp", fake_update)

    reply, log_info = handle_use_item(acct, "수상한 물약", None, 2, state)

    assert (
        "체력이 10 회복된다. 그리고…… 체력이 20 회복된다. (80/100)" in reply
    )  # 50 + (10 + 20), max_hp=100
    assert len(update_calls) == 1
    assert recorded_hp == {"동료": 80}


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
    """ "기타"/"비전투 소모품"/"부적"은 코스트·사거리가 항상 0이므로
    [가방]에서 코스트/사거리 표기를 생략한다."""
    acct = "user1"
    state = _make_state(acct)
    key_item = ItemData(
        id="키 아이템",
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
            ("동료", "키 아이템"): 1,
            ("동료", "수상한 물약"): 1,
            ("동료", "행운의 부적"): 1,
        }
    )
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {
            "키 아이템": key_item,
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
    assert "▹ 키 아이템×1: 용도 불명의 양탄자." in reply
    assert "▹ 수상한 물약×1: 마셔 봐야 아는 물약." in reply
    assert "비전투 전용" not in reply
    assert "▹ 행운의 부적×1: 부적. 지니고 있으면 운이 좋아진다." in reply


def test_bag_shows_target_label_for_consumable_item(monkeypatch):
    """ "소모품"은 target_rule에 따라 "(대상라벨 · 코스트 N · 사거리 M)"
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


def test_handle_dice_single_reply_format(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(random, "randint", lambda a, b: 42)

    reply, log_info = handle_dice(acct, 1, "100", state)

    assert reply == "◊ 1d100 → 「42」"
    assert log_info is not None
    assert log_info.command_text == "[1D100]"
    assert log_info.dice_roll == "42"
    assert log_info.error_trace is None


def test_handle_dice_rolls_up_to_given_sides(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    calls = []

    def fake_randint(a, b):
        calls.append((a, b))
        return b

    monkeypatch.setattr(random, "randint", fake_randint)

    reply, log_info = handle_dice(acct, 1, "020", state)

    assert calls == [(1, 20)]
    assert reply == "◊ 1d20 → 「20」"
    assert log_info.command_text == "[1D20]"


def test_handle_dice_multiple_shows_each_roll(monkeypatch):
    acct = "user1"
    state = _make_state(acct)
    rolls = iter([1, 5, 3])
    calls = []

    def fake_randint(a, b):
        calls.append((a, b))
        return next(rolls)

    monkeypatch.setattr(random, "randint", fake_randint)

    reply, log_info = handle_dice(acct, 3, "6", state)

    assert calls == [(1, 6)] * 3
    assert reply == "◊ 3d6: 1 + 5 + 3 → 「9」"
    assert log_info.command_text == "[3D6]"
    assert log_info.dice_roll == "1 + 5 + 3"
    assert log_info.result == "「9」"


@pytest.mark.parametrize(
    ("count", "sides_text", "message"),
    [
        (1, "0", "주사위 면 수는 1 이상"),
        (1, "", "주사위 면 수는 1 이상"),
        (1, "n", "주사위 면 수는 1 이상"),
        (1, "-5", "주사위 면 수는 1 이상"),
        (1, "1000001", "주사위 면 수는 1 이상"),
        (1, "２０", "주사위 면 수는 1 이상"),
        (0, "6", "주사위 개수는 1개 이상"),
        (21, "6", "주사위 개수는 1개 이상"),
    ],
)
def test_handle_dice_rejects_invalid_input(monkeypatch, count, sides_text, message):
    acct = "user1"
    state = _make_state(acct)
    monkeypatch.setattr(
        random, "randint", lambda a, b: pytest.fail("잘못된 입력은 굴리지 않는다")
    )

    reply, log_info = handle_dice(acct, count, sides_text, state)

    assert message in reply
    assert log_info is not None
    assert log_info.dice_roll == ""


def test_handle_dice_rejects_unregistered_character():
    state = _make_state("user1")

    reply, log_info = handle_dice("unregistered_user", 1, "100", state)

    assert "등록된 캐릭터를 찾을 수 없습니다" in reply
    assert log_info is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("@bot [1d100]", (1, "100")),
        ("@bot [1D100]", (1, "100")),
        ("@bot 굴려 볼게 [ 1 d 20 ] 제발", (1, "20")),
        ("@bot [2d6]", (2, "6")),
        ("@bot [02D6]", (2, "6")),
        ("@bot [1d]", (1, "")),
        ("@bot [1dn]", (1, "n")),
        ("@bot [가방]", None),
        ("@bot [d6]", None),
        ("@bot [xd6]", None),
        ("@bot [1d6/2]", None),
        ("@bot [판정/육체]", None),
    ],
)
def test_parse_dice_command(text, expected):
    assert parse_dice_command(text) == expected


def test_investigation_menu_post_shares_session_across_accts():
    """여러 명이 참여한 스레드의 [상시조사]는 참여자 전원이 같은 세션에
    들어가야 그중 누가 답글을 보내든 이어진다."""
    state = _make_state("user1")

    session = finalize_investigation_menu_post(["user1", "user2"], 100, state)

    assert session.accts == ["user1", "user2"]
    assert state.noncombat.active_investigations("user1") == [session]
    assert state.noncombat.active_investigations("user2") == [session]


def test_investigation_sessions_run_in_parallel():
    """[상시조사]는 병행할 수 있다 — 새 세션을 열어도 같은 참여자의 이전
    세션은 그대로 이어진다(겹치면 안 되는 것은 의뢰 수주뿐이다)."""
    state = _make_state("user1")
    shared = finalize_investigation_menu_post(["user1", "user2"], 100, state)

    solo = finalize_investigation_menu_post(["user1"], 101, state)

    assert shared.accts == ["user1", "user2"]
    assert shared.ended is False
    assert state.noncombat.active_investigations("user1") == [shared, solo]


def _quest_accept_listener(monkeypatch, accts: list[str]):
    """user1이 accts[1:]을 멘션해 [상시조사]를 열고 [광장]으로 의뢰 개요까지
    받은 상태. accts는 전부 캐릭터 계정으로 등록된다."""
    from bot import main as main_module
    from test_bot_admin import _FakeMastodon

    state = _make_state(accts[0])
    for acct in accts[1:]:
        state.char_dict[acct] = get_test_preset("동료")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest(venue="광장")]),
    )
    taken_by: list[str] = []
    monkeypatch.setattr(
        noncombat_module,
        "update_quest_taken_by",
        lambda spreadsheet, quest_id, value, cache=None: taken_by.append(value),
    )
    monkeypatch.setattr(main_module, "_persist_noncombat_log", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    monkeypatch.setattr(
        mastodon, "status_context", lambda status_id: pytest.fail("스레드 조회")
    )
    listener = main_module.MastodonBotListener(mastodon, state, bot_acct="bot")
    dispatch = listener._MastodonBotListener__dispatch  # type: ignore[attr-defined]
    dispatch("user1", 1, 50, "[상시조사]", "public", ["user2"])
    [session] = state.noncombat.active_investigations("user1")
    listener._threads.record(2, session.menu_post_id, "user1")
    dispatch("user1", 2, session.menu_post_id, "[광장]", "public", [])
    assert session.overview_post_id is not None
    return listener, mastodon, dispatch, session, taken_by


def test_investigation_accept_puts_sender_first_even_if_not_starter(monkeypatch):
    """[상시조사]를 보낸 사람이 아니라 다른 참여자가 [수락]해도 그 발신자가
    맨 앞이고, 멘션을 지워도 세션 참여자는 빠지지 않는다(테스트)."""
    _listener, _mastodon, dispatch, session, taken_by = _quest_accept_listener(
        monkeypatch, ["user1", "user2"]
    )

    dispatch("user2", 3, session.overview_post_id, "[수락]", "public", [])

    assert taken_by == ["user2,user1"]
    assert session.ended is True


def test_investigation_accept_registers_everyone_in_thread(monkeypatch):
    """[수락]에 멘션하지 않았어도 메뉴 이후 스레드에 글을 쓴 캐릭터는 전원
    참여자가 된다. world처럼 캐릭터가 아닌 작성자는 빠진다(테스트)."""
    listener, mastodon, dispatch, session, taken_by = _quest_accept_listener(
        monkeypatch, ["user1", "user2", "user3"]
    )
    # 사담 게시물 id는 스레드 조상 판정이 시각 순서로 보므로 봇 게시물보다 크다.
    listener._threads.record(9103, session.overview_post_id, "user3")
    listener._threads.record(9104, 9103, "test-world")
    listener._threads.record(9105, 9104, "user1")

    dispatch("user1", 9106, 9105, "[수락]", "public", [])

    assert taken_by == ["user1,user2,user3"]
    assert mastodon.status_post_calls[-1]["status"].startswith("@user1 @user2 @user3 ")


def test_investigation_accept_from_outsider_is_accepted(monkeypatch):
    """[상시조사] 세션 참여자가 아닌 캐릭터가 [수락]해도 받고, 그 시점의
    스레드 참여자 전원이 기록된다(테스트)."""
    listener, _mastodon, dispatch, session, taken_by = _quest_accept_listener(
        monkeypatch, ["user1", "user2", "user3", "user4"]
    )
    listener._threads.record(9103, session.overview_post_id, "user3")

    dispatch("user4", 9104, 9103, "[수락]", "public", [])

    assert taken_by == ["user4,user1,user2,user3"]
    assert session.ended is True


def test_outsider_accept_outside_overview_is_ignored(monkeypatch):
    """세션 참여자가 아닌 캐릭터의 [수락]은 의뢰 개요 단계에서만 받는다 —
    장소 선택 메뉴에 단 [수락]은 그 세션을 건드리지 않는다(테스트)."""
    from bot import main as main_module
    from test_bot_admin import _FakeMastodon

    state = _make_state("user1")
    state.char_dict["user4"] = get_test_preset("동료")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest(venue="광장")]),
    )
    monkeypatch.setattr(
        noncombat_module,
        "update_quest_taken_by",
        lambda *a, **k: pytest.fail("수주 기록"),
    )
    monkeypatch.setattr(main_module, "_persist_noncombat_log", lambda *a, **k: None)
    # 세션에 걸리지 않은 [수락]은 아이템 이름으로 읽히는 경로까지 내려간다.
    monkeypatch.setattr(main_module, "parse_bare_item_command", lambda *a: None)
    mastodon = _FakeMastodon()
    listener = main_module.MastodonBotListener(mastodon, state, bot_acct="bot")
    dispatch = listener._MastodonBotListener__dispatch  # type: ignore[attr-defined]
    dispatch("user1", 1, 50, "[상시조사]", "public", [])
    [session] = state.noncombat.active_investigations("user1")

    dispatch("user4", 2, session.menu_post_id, "[수락]", "public", [])

    assert session.ended is False
    assert session.quest_id is None


def test_investigation_start_tracks_all_mentioned_characters(monkeypatch):
    """[상시조사]에 멘션된 캐릭터 전원을 멘션하고 세션에 올려, 다른 참여자의
    장소 선택도 반영돼야 한다. world처럼 캐릭터가 아닌 계정은 참여자로 잡지
    않는다."""
    from bot import main as main_module
    from test_bot_admin import _FakeMastodon

    state = _make_state("user1")
    state.char_dict["user2"] = get_test_preset("동료")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest(venue="광장")]),
    )
    monkeypatch.setattr(main_module, "_persist_noncombat_log", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    monkeypatch.setattr(
        mastodon, "status_context", lambda status_id: pytest.fail("스레드 조회")
    )
    listener = main_module.MastodonBotListener(mastodon, state, bot_acct="bot")
    dispatch = listener._MastodonBotListener__dispatch  # type: ignore[attr-defined]

    dispatch("user1", 1, 50, "[상시조사]", "public", ["test-world", "user2"])

    menu_post = mastodon.status_post_calls[-1]
    assert menu_post["status"].startswith("@user1 @user2 ")
    [session] = state.noncombat.active_investigations("user2")
    assert session.accts == ["user1", "user2"]
    assert state.noncombat.active_investigations("test-world") == []

    dispatch("user2", 2, session.menu_post_id, "[광장]", "public", [])

    overview_post = mastodon.status_post_calls[-1]
    # 답글을 단 user2가 맨 앞이다.
    assert overview_post["status"].startswith("@user2 @user1 ")
    assert session.quest_id == "항구 마을_운반"


def _investigation_menu_listener(monkeypatch):
    from bot import main as main_module
    from test_bot_admin import _FakeMastodon

    state = _make_state("user1")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest(venue="광장")]),
    )
    monkeypatch.setattr(main_module, "_persist_noncombat_log", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    monkeypatch.setattr(
        mastodon, "status_context", lambda status_id: pytest.fail("스레드 조회")
    )
    listener = main_module.MastodonBotListener(mastodon, state, bot_acct="bot")
    dispatch = listener._MastodonBotListener__dispatch  # type: ignore[attr-defined]
    dispatch("user1", 1, 50, "[상시조사]", "public", [])
    [session] = state.noncombat.active_investigations("user1")
    return state, mastodon, dispatch, session


def test_lone_dice_roll_takes_priority_over_thread_context(monkeypatch):
    """[1dN]만 적은 답글은 상시조사 장소 선택 단계에서도 장소 이름으로
    읽히지 않고 굴림으로 처리되며, 세션은 그대로 남는다."""
    state, mastodon, dispatch, session = _investigation_menu_listener(monkeypatch)
    monkeypatch.setattr(random, "randint", lambda a, b: 7)

    dispatch("user1", 2, session.menu_post_id, "[1d20]", "public", [])

    assert mastodon.status_post_calls[-1]["status"].endswith("◊ 1d20 → 「7」")
    assert session.quest_id is None
    assert state.noncombat.active_investigations("user1") == [session]


def test_dice_with_other_command_does_not_hijack_it(monkeypatch):
    """다른 커맨드와 함께 적은 [1dN]은 그 맥락의 커맨드를 가로채지 않는다."""
    state, mastodon, dispatch, session = _investigation_menu_listener(monkeypatch)

    dispatch("user1", 2, session.menu_post_id, "[광장] [1d20]", "public", [])

    assert "1d20" not in mastodon.status_post_calls[-1]["status"]
    assert session.quest_id == "항구 마을_운반"


def _put_in_main_battle(state: BotState, char_name: str) -> None:
    from battle.objects.define import BattlefieldColumnIndex, FactionType
    from bot.session import BattleSession

    state.session = BattleSession({}, {})
    state.session.context.add_character(
        get_test_preset(char_name), FactionType.ALLY, BattlefieldColumnIndex(0)
    )


def _put_in_practice(state: BotState, char_name: str, mode) -> None:
    from battle.objects.define import BattlefieldColumnIndex
    from battle.practice.context import PracticeBattlefieldContext
    from battle.practice.define import SideType
    from battle.practice.round_manager import PracticeRoundManager
    from bot.practice_state import PracticeBattleState

    context = PracticeBattlefieldContext({}, {}, mode=mode)
    context.add_character(
        get_test_preset(char_name), SideType.SIDE_1, BattlefieldColumnIndex(0)
    )
    state.practices[1] = PracticeBattleState(
        context=context, manager=PracticeRoundManager(context), mode=mode
    )


def _stub_item_sheets(monkeypatch, item: ItemData, inventory: Inventory) -> list:
    recorded_hp: list = []
    monkeypatch.setattr(
        noncombat_module,
        "load_item_data",
        lambda spreadsheet, cache=None: {item.id: item},
    )
    monkeypatch.setattr(
        noncombat_module, "load_inventory", lambda spreadsheet, cache=None: inventory
    )
    monkeypatch.setattr(
        noncombat_module,
        "update_character_curr_hp",
        lambda spreadsheet, name, hp, cache=None: recorded_hp.append((name, hp)),
    )
    return recorded_hp


def test_use_item_rejected_for_main_battle_participant(monkeypatch, potion_item):
    state = _make_state_with_name_dict("user1", "동료", curr_hp=50)
    _put_in_main_battle(state, "동료")
    inventory = Inventory({("동료", "포션"): 1})
    recorded_hp = _stub_item_sheets(monkeypatch, potion_item, inventory)

    reply, _log = handle_use_item("user1", "포션", None, 1, state)

    assert reply == "◊ 전투 도중에는 전투 커맨드로만 아이템을 사용할 수 있습니다."
    assert recorded_hp == []
    assert inventory.get_count("동료", "포션") == 1


def test_use_item_rejected_when_target_is_in_battle(monkeypatch, potion_item):
    state = _make_state_with_name_dict("user1", "동료", curr_hp=50)
    state.name_dict["참전자"] = get_test_preset("참전자", initial_hp=50)
    _put_in_main_battle(state, "참전자")
    inventory = Inventory({("동료", "포션"): 1})
    recorded_hp = _stub_item_sheets(monkeypatch, potion_item, inventory)

    reply, _log = handle_use_item("user1", "포션", "참전자", 1, state)

    assert reply == "◊ 전투 도중에는 전투 커맨드로만 아이템을 사용할 수 있습니다."
    assert recorded_hp == []
    assert inventory.get_count("동료", "포션") == 1


def test_use_item_allowed_during_investigation_battle(monkeypatch, potion_item):
    from battle.practice.define import PracticeBattleMode

    state = _make_state_with_name_dict("user1", "동료", curr_hp=50)
    _put_in_practice(state, "동료", PracticeBattleMode.INVESTIGATION)
    inventory = Inventory({("동료", "포션"): 1})
    recorded_hp = _stub_item_sheets(monkeypatch, potion_item, inventory)

    handle_use_item("user1", "포션", None, 1, state)

    assert recorded_hp == [("동료", 70)]


def test_transfer_item_rejected_when_receiver_in_main_battle(monkeypatch, potion_item):
    state = _make_state_with_name_dict("user1", "동료", curr_hp=50)
    state.name_dict["동료2"] = get_test_preset("동료2")
    _put_in_main_battle(state, "동료2")
    inventory = Inventory({("동료", "포션"): 3})
    _stub_item_sheets(monkeypatch, potion_item, inventory)

    reply, _log = handle_transfer_item("user1", "포션", "동료2", 1, state)

    assert reply == "◊ 전투 도중에는 아이템을 양도할 수 없습니다."
    assert inventory.get_count("동료", "포션") == 3
    assert inventory.get_count("동료2", "포션") == 0


def test_transfer_item_allowed_during_investigation_battle(monkeypatch, potion_item):
    from battle.practice.define import PracticeBattleMode

    state = _make_state_with_name_dict("user1", "동료", curr_hp=50)
    state.name_dict["동료2"] = get_test_preset("동료2")
    _put_in_practice(state, "동료2", PracticeBattleMode.INVESTIGATION)
    inventory = Inventory({("동료", "포션"): 3})
    _stub_item_sheets(monkeypatch, potion_item, inventory)

    handle_transfer_item("user1", "포션", "동료2", 1, state)

    assert inventory.get_count("동료2", "포션") == 1


def test_investigation_accept_rejects_more_than_four_participants(monkeypatch):
    state = _make_state("user1")
    session = _investigation_session(acct="user1", quest_id="항구 마을_운반")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest()]),
    )
    calls: list = []
    monkeypatch.setattr(
        noncombat_module,
        "update_quest_taken_by",
        lambda *a, **k: calls.append(a),
    )

    result, _log = handle_investigation_accept(
        session, ["user1", "user2", "user3", "user4", "user5"], state
    )

    assert result.startswith("◊ 의뢰 하나에는 최대 4명까지 참여할 수 있습니다.")
    assert calls == []
    assert session.ended is False


def test_investigation_accept_allows_exactly_four_participants(monkeypatch):
    state = _make_state("user1")
    session = _investigation_session(acct="user1", quest_id="항구 마을_운반")
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quest_sheet",
        lambda spreadsheet, cache=None: (_quest_location(), [_quest()]),
    )
    calls: list = []
    monkeypatch.setattr(
        noncombat_module,
        "update_quest_taken_by",
        lambda spreadsheet, quest_id, taken_by, cache=None: calls.append(taken_by),
    )

    handle_investigation_accept(session, ["user1", "user2", "user3", "user4"], state)

    assert calls == ["user1,user2,user3,user4"]


def _daily_quest_listener(monkeypatch, acct="user1", quest_post_id=500):
    from bot import main as main_module
    from test_bot_admin import _FakeMastodon

    state = _make_state(acct)
    state.noncombat.daily_quest_mid[acct] = DailyQuestMidState(
        bot_reply_post_id=quest_post_id
    )
    monkeypatch.setattr(
        noncombat_module, "update_character_quest_date", lambda *a, **k: None
    )
    monkeypatch.setattr(noncombat_module, "append_ledger_row", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "_persist_noncombat_log", lambda *a, **k: None)
    mastodon = _FakeMastodon()
    listener = main_module.MastodonBotListener(mastodon, state, bot_acct="bot")
    dispatch = listener._MastodonBotListener__dispatch  # type: ignore[attr-defined]
    return state, mastodon, listener, dispatch


def test_daily_quest_roll_accepted_after_intermediate_reply_in_thread(monkeypatch):
    """의뢰 ← 주사위 굴림 ← 판정처럼 사이에 답글이 끼어도 같은 스레드면 일일
    의뢰 판정으로 처리돼야 한다 — 독립 판정으로 빠지면 의뢰가 끝나지 않는다(테스트)."""
    state, mastodon, listener, dispatch = _daily_quest_listener(monkeypatch)
    listener._threads.record(501, 500, "user1")  # 의뢰 ← 1d2
    listener._threads.record(502, 501, "dice")  # 1d2 ← 굴림 결과

    dispatch("user1", 503, 502, "[판정/육체]", "public", [])

    assert "user1" not in state.noncombat.daily_quest_mid
    assert "사례로 1G를 획득했다" in mastodon.status_post_calls[-1]["status"]


def test_daily_quest_roll_ignores_other_characters_quest_thread(monkeypatch):
    """조상 경로로는 자기 의뢰 안내 게시물만 찾는다 — 남의 의뢰 스레드 깊은 곳에서
    한 판정이 내 의뢰를 끝내면 안 된다(테스트)."""
    state, mastodon, listener, dispatch = _daily_quest_listener(monkeypatch)
    state.noncombat.daily_quest_mid["user2"] = DailyQuestMidState(bot_reply_post_id=600)
    listener._threads.record(601, 600, "user2")

    dispatch("user1", 602, 601, "[판정/육체]", "public", [])

    assert "user1" in state.noncombat.daily_quest_mid
    assert "사례로 1G를 획득했다" not in mastodon.status_post_calls[-1]["status"]


def test_daily_quest_thread_lookup_skipped_without_roll_command(monkeypatch):
    """[판정]이 아닌 답글은 스레드 조상을 조회하지 않는다(테스트)."""
    state, mastodon, listener, dispatch = _daily_quest_listener(monkeypatch)
    monkeypatch.setattr(mastodon, "status", lambda status_id: pytest.fail("조회"))

    dispatch("user1", 502, 501, "1d2 굴려 볼까", "public", [])

    assert "user1" in state.noncombat.daily_quest_mid
