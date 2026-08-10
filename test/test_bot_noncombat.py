import os

os.environ.setdefault("ADMIN_MASTODON_ID", "test-admin")

import random  # noqa: E402

import pytest  # noqa: E402
from battle.objects.define import ValueSourceType, ValueType  # noqa: E402
from battle.objects.item.models import ItemData  # noqa: E402
from battle.objects.skill.effects import SkillEffectDamage, SkillEffectHeal  # noqa: E402
from bot import commands as _  # noqa: E402, F401
from bot.commands import noncombat as noncombat_module  # noqa: E402
from bot.commands.noncombat import (  # noqa: E402
    handle_daily_quest_roll,
    handle_daily_quest_start,
    handle_investigation_accept,
    handle_investigation_venue_choice,
    handle_roll,
    handle_transfer_item,
    handle_use_item,
    parse_transfer_item_args,
    parse_use_item_args,
)
from bot.main import BotState  # noqa: E402
from bot.noncombat_state import DailyQuestMidState  # noqa: E402
from helpers import get_test_preset  # noqa: E402
from spreadsheets.inventory import Inventory  # noqa: E402
from spreadsheets.models.noncombat import NoncombatCharacterDataFromSpreadsheet  # noqa: E402
from spreadsheets.models.quest import (  # noqa: E402
    DailyQuestPools,
    DailyQuestResultMessageData,
    DailyQuestSuccessType,
    QuestData,
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


def test_handle_investigation_accept_returns_log_info():
    """[수락]도 마찬가지로 NoncombatLogInfo를 반환해 로그에 남아야 한다."""
    acct = "user1"
    state = _make_state(acct)
    state.noncombat.investigation_acct_to_quest_id[acct] = "q1"

    result, log_info = handle_investigation_accept(acct, state)

    assert "수주했습니다" in result
    assert log_info is not None
    assert log_info.command_text == "[수락]"


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
            quest_contents=("부모를 찾아 달라는",),
        ),
    )

    result, log_info = handle_daily_quest_start(acct, state)

    assert result.startswith(
        "길 잃은 어린아이로부터 부모를 찾아 달라는 의뢰를 맡겼다. 어떻게 할까?"
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
            quest_contents=("세금 장부를 정리해 달라는",),
        ),
    )

    result, log_info = handle_daily_quest_start(acct, state)

    assert result.startswith(
        "마을 촌장으로부터 세금 장부를 정리해 달라는 의뢰를 맡겼다. 어떻게 할까?"
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
                "무거운 짐을 옮겨 달라는",
                "약초를 채집해 달라는",
                "순찰해 달라는",
            ),
        ),
    )

    result, log_info = handle_daily_quest_start(acct, state)

    assert result.startswith(
        "장터 아주머니로부터 무거운 짐을 옮겨 달라는 의뢰를 맡겼다. 어떻게 할까?"
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
    state.noncombat.investigation_venue_to_quest = {"장소A": "q1"}
    monkeypatch.setattr(
        noncombat_module,
        "load_general_quests",
        lambda spreadsheet, cache=None: [
            QuestData(
                id="q1",
                name="퀘스트1",
                description="설명",
                type="탐사",
                subtype="상시",
                location="",
                venue_name="장소A",
                reward="10G",
                available_until="",
            )
        ],
    )

    # 1. 유효한 장소를 선택 → quest_id가 저장된다
    handle_investigation_venue_choice(acct, "장소A", state)
    assert state.noncombat.investigation_acct_to_quest_id.get(acct) == "q1"

    # 2. 같은 메뉴에 존재하지 않는 장소를 다시 입력 → 실패 응답이지만
    #    이전에 저장된 quest_id는 지워져야 한다
    result, log_info = handle_investigation_venue_choice(
        acct, "존재하지 않는 장소", state
    )

    assert "이번 조사의 장소가 아닙니다" in result
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
        usable_outside_battle=True,
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
        usable_outside_battle=True,
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
    """usable_outside_battle=True라도 회복이 아닌 효과(대미지 등)는 비전투에서 지원하지 않는다."""
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


def test_use_item_rejects_when_not_usable_outside_battle(monkeypatch, potion_item):
    from dataclasses import replace

    acct = "user1"
    state = _make_state_with_name_dict(acct, "동료", curr_hp=50)
    battle_only_potion = replace(potion_item, usable_outside_battle=False)
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

    assert "사용할 수 없습니다" in reply
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
