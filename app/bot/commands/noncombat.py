import random
import re
import traceback
from datetime import date
from typing import TYPE_CHECKING, Optional

from battle.objects.define import ValueSourceType
from battle.objects.skill.effects import SkillEffectHeal
from spreadsheets.models.noncombat import NON_COMBAT_STATS, NoncombatStatType
from spreadsheets.models.quest import DailyQuestSuccessType
from utils.name_matching import resolve_matching_key, whitespace_tolerant_literal

from bot.load_data import (
    load_daily_quest_result_messages,
    load_daily_quests,
    load_general_quests,
    load_inventory,
    load_item_data,
    load_location_and_investigation,
    update_character_curr_hp,
    update_character_gold_and_quest_date,
)
from bot.log_sheets import NoncombatLogInfo
from bot.noncombat_state import (
    DailyQuestMidState,
    InvestigationQuestStatus,
)

if TYPE_CHECKING:
    from bot.main import BotState

_RE_ROLL = re.compile(rf"\[{whitespace_tolerant_literal('판정')}\s*/\s*([^]]+)]")
_RE_USE_ITEM = re.compile(rf"\[{whitespace_tolerant_literal('사용')}\s*/\s*([^\]]+)]")
_RE_TRANSFER_ITEM = re.compile(
    rf"\[{whitespace_tolerant_literal('양도')}\s*/\s*([^\]]+)]"
)

FREE_EXPLORE_LABEL = "그 외의 장소를 찾아본다."


def parse_stat_name(text: str) -> Optional[str]:
    """텍스트에서 [판정/스탯] 패턴을 찾아 스탯 이름을 반환한다."""
    m = _RE_ROLL.search(text)
    return m.group(1).strip() if m else None


def parse_use_item_args(text: str) -> Optional[tuple[str, Optional[str], int]]:
    """텍스트에서 [사용/아이템(/대상)(/개수)] 패턴을 찾아 (아이템명, 대상 또는 None, 개수)를 반환한다."""
    m = _RE_USE_ITEM.search(text)
    if not m:
        return None
    return _parse_item_args(m.group(1))


def parse_transfer_item_args(text: str) -> Optional[tuple[str, Optional[str], int]]:
    """텍스트에서 [양도/아이템/대상(/개수)] 패턴을 찾아 (아이템명, 대상 또는 None, 개수)를 반환한다."""
    m = _RE_TRANSFER_ITEM.search(text)
    if not m:
        return None
    return _parse_item_args(m.group(1))


def _parse_item_args(raw: str) -> tuple[str, Optional[str], int]:
    """'아이템명(/대상)(/개수)' 형태를 파싱한다. 대상·개수는 순서 무관하게 인식한다."""
    tokens = [t.strip() for t in raw.split("/") if t.strip()]
    item_name = tokens[0] if tokens else ""
    target: Optional[str] = None
    count = 1
    for token in tokens[1:]:
        count_match = re.fullmatch(r"(\d+)\s*개?", token)
        if count_match:
            count = int(count_match.group(1))
        else:
            target = token
    return item_name, target, count


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------


def handle_roll(
    acct: str, stat_name: str, state: "BotState"
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[판정/스탯] → 1d6 + 스탯값 계산 후 결과 텍스트 반환."""
    command_text = f"[판정/{stat_name}]"
    if stat_name not in NON_COMBAT_STATS:
        msg = f"◊ 알 수 없는 스탯입니다. 사용 가능한 스탯: {'·'.join(NON_COMBAT_STATS)}"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    stat_type = NoncombatStatType(stat_name)
    stat_val = char_data.get_noncombat_stat(stat_type)
    dice = random.randint(1, 6)
    total = dice + stat_val
    reply = f"[{stat_name}] {dice}+{stat_val} → 「{total}」"
    return reply, NoncombatLogInfo(
        command_text=command_text,
        dice_roll=f"{dice}+{stat_val}",
        result=f"「{total}」",
    )


# ---------------------------------------------------------------------------
# 비전투 아이템 사용/양도
# ---------------------------------------------------------------------------


def _compute_heal_amount(
    effect: SkillEffectHeal, target_max_hp: int, count: int
) -> Optional[int]:
    """비전투에서 지원하는 value_source(고정값/최대 체력 %)에 한해 회복량을 계산한다."""
    if effect.value_source == ValueSourceType.FIXED:
        return (effect.value or 0) * count
    if effect.value_source == ValueSourceType.STAT_MAX_HP:
        return (target_max_hp * (effect.value or 0) // 100) * count
    return None


def handle_use_item(
    acct: str,
    item_name: str,
    target_name: Optional[str],
    count: int,
    state: "BotState",
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[사용/아이템(/대상)(/개수)] → 비전투 상황에서 즉시 아이템 효과를 적용한다.

    현재는 회복(Heal) 효과만 지원한다.
    """
    command_text = (
        f"[사용/{item_name}"
        + (f"/{target_name}" if target_name else "")
        + f"/{count}개]"
    )

    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    user_name = char_data.name
    target_char_name = target_name or user_name

    try:
        item_dict = load_item_data(state.spreadsheet, cache=state.sheet_cache)
        inventory = load_inventory(state.spreadsheet, cache=state.sheet_cache)
        inventory.cache = state.sheet_cache
    except Exception as e:
        msg = f"◊ 아이템 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    item_name = resolve_matching_key(item_name, item_dict.keys())
    item = item_dict.get(item_name)
    if item is None:
        msg = f"◊ 아이템 '{item_name}'을(를) 찾을 수 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)
    if not item.usable_outside_battle:
        msg = f"◊ '{item_name}'은(는) 비전투 상황에서 사용할 수 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)
    if not isinstance(item.effect, SkillEffectHeal):
        msg = f"◊ '{item_name}'은(는) 비전투 상황에서 지원하지 않는 효과입니다. (회복 아이템만 사용 가능)"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    owned = inventory.get_count(user_name, item_name)
    if owned < count:
        msg = f"◊ 보유한 「{item_name}」의 수가 부족합니다. (현재 {owned}개)"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    target_char_name = resolve_matching_key(target_char_name, state.name_dict.keys())
    target_data = state.name_dict.get(target_char_name)
    if target_data is None:
        msg = f"◊ 대상 캐릭터('{target_char_name}')를 찾을 수 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    heal_amount = _compute_heal_amount(item.effect, target_data.max_hp, count)
    if heal_amount is None:
        msg = f"◊ '{item_name}'의 회복 방식은 비전투 상황에서 지원하지 않습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)
    # heal_amount가 not None이면 _compute_heal_amount()가 FIXED/STAT_MAX_HP
    # 분기를 탔다는 뜻이므로 value_source도 이미 채워져 있다.
    assert item.effect.value_source is not None

    prev_hp = target_data.curr_hp or 0
    new_hp = min(target_data.max_hp, prev_hp + heal_amount)

    try:
        update_character_curr_hp(
            state.spreadsheet, target_char_name, new_hp, cache=state.sheet_cache
        )
        inventory.consume(user_name, item_name, count)
    except Exception as e:
        msg = f"◊ 아이템 사용 처리 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    result_text = f"{target_char_name}의 체력을 {heal_amount} 회복했습니다. ({prev_hp} → {new_hp})"
    reply = f"◊ '{item_name}' 사용: {result_text}"
    return reply, NoncombatLogInfo(
        command_text=command_text,
        dice_roll=f"{item.effect.value_source.value}×{count}",
        result=result_text,
    )


def handle_transfer_item(
    acct: str,
    item_name: str,
    target_name: Optional[str],
    count: int,
    state: "BotState",
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[양도/아이템/대상(/개수)] → 대상에게 아이템을 양도하고 인벤토리를 갱신한다."""
    command_text = f"[양도/{item_name}/{target_name}/{count}개]"

    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    user_name = char_data.name

    if not target_name:
        msg = "◊ 양도할 대상을 지정해 주세요. 예: [양도/포션/동료]"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    target_name = resolve_matching_key(target_name, state.name_dict.keys())
    if target_name not in state.name_dict:
        msg = f"◊ 대상 캐릭터('{target_name}')를 찾을 수 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        item_dict = load_item_data(state.spreadsheet, cache=state.sheet_cache)
        inventory = load_inventory(state.spreadsheet, cache=state.sheet_cache)
        inventory.cache = state.sheet_cache
    except Exception as e:
        msg = f"◊ 아이템 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    item_name = resolve_matching_key(item_name, item_dict.keys())
    if item_name not in item_dict:
        msg = f"◊ 아이템 '{item_name}'을(를) 찾을 수 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    owned = inventory.get_count(user_name, item_name)
    if owned < count:
        msg = f"◊ 보유한 「{item_name}」의 수가 부족합니다. (현재 {owned}개)"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        inventory.consume(user_name, item_name, count)
        inventory.grant(target_name, item_name, count)
    except Exception as e:
        msg = f"◊ 아이템 양도 처리 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    result_text = f"{user_name} → {target_name}에게 '{item_name}' {count}개 양도"
    reply = f"◊ {target_name}에게 「{item_name}」 {count}개를 양도했습니다."
    return reply, NoncombatLogInfo(command_text=command_text, result=result_text)


# ---------------------------------------------------------------------------
# 일일 의뢰
# ---------------------------------------------------------------------------


def handle_daily_quest_start(
    acct: str, state: "BotState"
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[의뢰] → 오늘 이미 했으면 거절 / 아니면 랜덤 의뢰 내용 반환."""
    command_text = "[의뢰]"
    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    today = date.today().isoformat()
    if char_data.daily_quest_date == today:
        msg = "◊ 오늘 이미 의뢰를 수행했습니다. 내일 다시 도전해 주세요!"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        location, investigation_active, _, _ = load_location_and_investigation(
            state.spreadsheet, cache=state.sheet_cache
        )
        daily_quests = load_daily_quests(state.spreadsheet, cache=state.sheet_cache)
    except Exception as e:
        msg = f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    pool = [
        q
        for q in daily_quests
        if investigation_active and (not q.location or q.location == location)
    ]
    if not pool:
        msg = "◊ 현재 위치에서 받을 수 있는 의뢰가 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    quest = random.choice(pool)

    state.noncombat.daily_quest_mid[acct] = DailyQuestMidState(
        quest_id=quest.id, bot_reply_post_id=0
    )

    reply = (
        f"{quest.client_name} {quest.description} 의뢰를 받았다. 어떻게 할까?\n"
        "\n◊ [판정/(원하는 비전투 스테이터스)] 형식으로 답글을 달아 의뢰를 수행할 수 있습니다."
    )
    return reply, NoncombatLogInfo(
        command_text=command_text, result=f"의뢰 배정: {quest.id} ({quest.client_name})"
    )


def finalize_daily_quest_mid(acct: str, post_id: int, state: "BotState") -> None:
    """봇이 의뢰 안내 게시물을 올린 뒤, 해당 포스트 ID를 mid_state에 기록한다."""
    mid = state.noncombat.daily_quest_mid.get(acct)
    if mid is not None:
        mid.bot_reply_post_id = post_id


def handle_daily_quest_roll(
    acct: str, stat_name: str, state: "BotState"
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """일일 의뢰 판정 답글 → 굴림 결과 + 1G 지급 + 스프레드시트 업데이트."""
    command_text = f"[판정/{stat_name}] (일일 의뢰)"
    if stat_name not in NON_COMBAT_STATS:
        msg = f"◊ 알 수 없는 스탯입니다. 사용 가능한 스탯: {'·'.join(NON_COMBAT_STATS)}"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    mid = state.noncombat.daily_quest_mid.get(acct)
    if mid is None:
        msg = "◊ 진행 중인 의뢰가 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    stat_type = NoncombatStatType(stat_name)
    stat_val = char_data.get_noncombat_stat(stat_type)
    dice = random.randint(1, 6)
    total = dice + stat_val

    if total >= 7:
        success_type = DailyQuestSuccessType.GREAT_SUCCESS
    elif total >= 5:
        success_type = DailyQuestSuccessType.SUCCESS
    else:
        success_type = DailyQuestSuccessType.CLOSE_SUCCESS

    try:
        result_messages = load_daily_quest_result_messages(
            state.spreadsheet, cache=state.sheet_cache
        )
        pool = [m for m in result_messages if m.success_type == success_type]
        message = random.choice(pool).message if pool else None
    except Exception:
        message = None

    judgment = (
        f"{success_type.value}! {message}" if message else f"{success_type.value}!"
    )

    new_gold = char_data.gold + 1
    today = date.today().isoformat()

    errors: list[str] = []
    save_succeeded = True
    save_error_trace: Optional[str] = None
    try:
        update_character_gold_and_quest_date(
            state.spreadsheet, char_data.name, new_gold, today, cache=state.sheet_cache
        )
    except Exception as e:
        save_succeeded = False
        save_error_trace = traceback.format_exc()
        errors.append(f"스프레드시트 저장 실패: {e}")

    # 저장에 실패하면 mid 상태를 남겨 두어 같은 게시물에 재시도할 수 있게 한다.
    if save_succeeded:
        del state.noncombat.daily_quest_mid[acct]

    result = f"[{stat_name}] {dice}+{stat_val} → 「{total}」\n{judgment}\n"
    if save_succeeded:
        result += "\n의뢰를 완수했다. 사례로 1G를 획득했다."
    else:
        result += (
            "의뢰 결과 저장에 실패했습니다. 이 답글에 다시 답글로 재시도해 주세요."
        )
    if errors:
        result += "\n◊ " + "; ".join(errors)
    return result, NoncombatLogInfo(
        command_text=command_text,
        dice_roll=f"{dice}+{stat_val}",
        result=f"「{total}」 {judgment}" + ("" if save_succeeded else " (저장 실패)"),
        error_trace=save_error_trace,
    )


# ---------------------------------------------------------------------------
# 상시조사
# ---------------------------------------------------------------------------


def handle_investigation_start(
    acct: str, state: "BotState"
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[상시조사] → 현위치 시트를 읽어 4개 선택지 메뉴 반환."""
    command_text = "[상시조사]"
    nc = state.noncombat

    if nc.investigation_accepted.get(acct):
        msg = "◊ 이번 구간에서 이미 의뢰를 수주했습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        location, investigation_active, venues, venue_desc = (
            load_location_and_investigation(state.spreadsheet, cache=state.sheet_cache)
        )
    except Exception as e:
        msg = f"◊ 조사 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    if not investigation_active or not venues:
        msg = "◊ 현재 상시조사를 진행할 수 없는 구간입니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        general_quests = load_general_quests(state.spreadsheet, cache=state.sheet_cache)
    except Exception as e:
        msg = f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    # venue → quest_id 매핑 갱신 (location 우선 매칭, 없으면 location 무관)
    venue_to_quest: dict[str, str] = {}
    for venue in venues:
        matches = [
            q
            for q in general_quests
            if q.venue_name == venue and (not location or q.location == location)
        ]
        if not matches:
            matches = [q for q in general_quests if q.venue_name == venue]
        if matches:
            venue_to_quest[venue] = matches[0].id
    nc.investigation_venue_to_quest = venue_to_quest
    nc.investigation_venue_to_desc = venue_desc

    lines = ["어디로 가 볼까?"]
    for venue in venues:
        lines.append(f"▸ [{venue}]")
    lines.append(f"▸ {FREE_EXPLORE_LABEL} (자율 탐사)")
    reply = "\n".join(lines)
    return reply, NoncombatLogInfo(
        command_text=command_text, result=f"메뉴 제공: {', '.join(venues)}"
    )


def finalize_investigation_menu_post(
    acct: str, post_id: int, state: "BotState"
) -> None:
    state.noncombat.investigation_menu_post_id[acct] = post_id


def handle_investigation_venue_choice(
    acct: str, venue_name: str, state: "BotState"
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """장소 선택 → 일반 의뢰 시트를 읽어 개요 반환."""
    command_text = f"[상시조사/{venue_name}]"
    nc = state.noncombat

    venue_name = resolve_matching_key(
        venue_name, nc.investigation_venue_to_quest.keys()
    )
    quest_id = nc.investigation_venue_to_quest.get(venue_name)
    if quest_id is None:
        # 이 답글은 유효한 의뢰 개요가 아니므로, 이전에 선택했던 의뢰가 남아 있다면
        # 지워 [수락] 시 엉뚱한(예전) 의뢰가 수주되는 것을 방지한다.
        nc.investigation_acct_to_quest_id.pop(acct, None)
        if "자율 탐사" in venue_name or venue_name == FREE_EXPLORE_LABEL:
            msg = "자유롭게 일대를 돌아다니며 정보를 수집할 수 있습니다."
            return msg, NoncombatLogInfo(command_text=command_text, result=msg)
        msg = f"◊ '{venue_name}'은(는) 이번 조사의 장소가 아닙니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        general_quests = load_general_quests(state.spreadsheet, cache=state.sheet_cache)
    except Exception as e:
        nc.investigation_acct_to_quest_id.pop(acct, None)
        msg = f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    quest_dict = {q.id: q for q in general_quests}
    quest = quest_dict.get(quest_id)
    if quest is None:
        nc.investigation_acct_to_quest_id.pop(acct, None)
        msg = "◊ 의뢰 정보를 찾을 수 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    existing = nc.quest_status.get(quest_id)
    if existing and existing.participants:
        nc.investigation_acct_to_quest_id.pop(acct, None)
        desc = nc.investigation_venue_to_desc.get(venue_name, "")
        lines = [f"[{venue_name}]에서는 이미 누군가가 의뢰를 수주했습니다."]
        if desc:
            lines.append(desc)
        lines.append("자율 탐사를 진행할 수 있습니다.")
        reply = "\n".join(lines)
        return reply, NoncombatLogInfo(
            command_text=command_text, result=f"{venue_name}: 이미 수주된 의뢰"
        )

    nc.investigation_acct_to_quest_id[acct] = quest_id

    reward_desc = quest.reward if quest.reward else "미정"
    lines = [
        f"[{venue_name}]에서 의뢰를 발견했습니다.",
        f"▸ 의뢰명: {quest.name}",
        f"▸ 계열: {quest.type} - {quest.subtype}",
    ]
    if quest.available_until:
        lines.append(f"▸ 클리어 가능 기간: {quest.available_until}")
    lines.append(f"▸ 보상: {reward_desc}")
    lines.append("")
    lines.append(quest.description)
    lines.append("")
    lines.append("이 의뢰를 수락할까?")
    lines.append("")
    lines.append("◊ 수락하려면 답글로 [수락]을 입력해 주세요.")
    reply = "\n".join(lines)
    return reply, NoncombatLogInfo(
        command_text=command_text, result=f"의뢰 개요 제공: {quest.name}"
    )


def finalize_investigation_overview_post(
    acct: str, post_id: int, state: "BotState"
) -> None:
    state.noncombat.investigation_overview_post_id[acct] = post_id


def handle_investigation_accept(
    acct: str,
    state: "BotState",
    in_reply_to_id: Optional[int] = None,
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[수락] → 의뢰 참여자 등록.

    자신의 탐사 흐름이거나, 이미 수락된 의뢰의 개요 게시물에 답글로 합류할 수 있다.
    """
    command_text = "[수락]"
    nc = state.noncombat

    if nc.investigation_accepted.get(acct):
        msg = "◊ 이번 구간에서 이미 의뢰를 수주했습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    quest_id = nc.investigation_acct_to_quest_id.get(acct)

    # 자신의 탐사 흐름이 없으면 in_reply_to_id로 타인의 의뢰에 합류
    if quest_id is None and in_reply_to_id is not None:
        for qid, status in nc.quest_status.items():
            if status.overview_post_id == in_reply_to_id:
                quest_id = qid
                break

    if quest_id is None:
        msg = "◊ 수락할 의뢰가 없습니다. 먼저 [상시조사]로 의뢰를 확인해 주세요."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    # 의뢰 이름을 일반 의뢰 시트에서 실시간 조회
    quest_name = quest_id
    try:
        general_quests = load_general_quests(state.spreadsheet, cache=state.sheet_cache)
        quest = next((q for q in general_quests if q.id == quest_id), None)
        if quest:
            quest_name = quest.name
    except Exception:
        pass

    if quest_id not in nc.quest_status:
        nc.quest_status[quest_id] = InvestigationQuestStatus(
            quest_id=quest_id,
            overview_post_id=nc.investigation_overview_post_id.get(acct, 0),
        )

    status = nc.quest_status[quest_id]
    if acct not in status.participants:
        status.participants.append(acct)

    nc.investigation_accepted[acct] = quest_id
    reply = f"◊ 수락 확인. 「{quest_name}」 의뢰를 수주했습니다."
    return reply, NoncombatLogInfo(
        command_text=command_text, result=f"의뢰 수주: {quest_name}"
    )
