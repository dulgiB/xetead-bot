import random
import re
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING, Optional

from spreadsheets.models.noncombat import NON_COMBAT_STATS, NoncombatStatType
from spreadsheets.models.quest import DailyQuestSuccessType

from bot.load_data import (
    load_daily_quest_result_messages,
    load_daily_quests,
    load_general_quests,
    load_location_and_investigation,
    update_character_gold_and_quest_date,
)
from bot.noncombat_state import (
    DailyQuestMidState,
    InvestigationQuestStatus,
)

if TYPE_CHECKING:
    from bot.main import BotState

_RE_ROLL = re.compile(r"\[판정\s*/\s*([^]]+)]")

FREE_EXPLORE_LABEL = "그 외의 장소를 찾아본다."


def parse_stat_name(text: str) -> Optional[str]:
    """텍스트에서 [판정/스탯] 패턴을 찾아 스탯 이름을 반환한다."""
    m = _RE_ROLL.search(text)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------


def handle_roll(acct: str, stat_name: str, state: "BotState") -> str:
    """[판정/스탯] → 1d6 + 스탯값 계산 후 결과 텍스트 반환."""
    if stat_name not in NON_COMBAT_STATS:
        return (
            f"◊ 알 수 없는 스탯입니다. 사용 가능한 스탯: {'·'.join(NON_COMBAT_STATS)}"
        )

    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다."

    stat_type = NoncombatStatType(stat_name)
    stat_val = char_data.get_noncombat_stat(stat_type)
    dice = random.randint(1, 6)
    return f"[{stat_name}] {dice}+{stat_val} → 「{dice + stat_val}」"


# ---------------------------------------------------------------------------
# 일일 의뢰
# ---------------------------------------------------------------------------


def handle_daily_quest_start(acct: str, state: "BotState") -> str:
    """[의뢰] → 오늘 이미 했으면 거절 / 아니면 랜덤 의뢰 내용 반환."""
    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다."

    today = date.today().isoformat()
    if char_data.daily_quest_date == today:
        return "◊ 오늘 이미 의뢰를 수행했습니다. 내일 다시 도전해 주세요!"

    try:
        location, _, _, _ = load_location_and_investigation(state.spreadsheet)
        daily_quests = load_daily_quests(state.spreadsheet)
    except Exception as e:
        return f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"

    pool = [q for q in daily_quests if not q.location or q.location == location]
    if not pool:
        return "◊ 현재 위치에서 받을 수 있는 의뢰가 없습니다."

    quest = random.choice(pool)

    state.noncombat.daily_quest_mid[acct] = DailyQuestMidState(
        quest_id=quest.id, bot_reply_post_id=0
    )

    return (
        f"{quest.description}\n"
        "어떻게 할까?\n"
        "(판정 방법: [판정/스탯] 형식으로 답글을 달아주세요.)"
    )


def finalize_daily_quest_mid(acct: str, post_id: int, state: "BotState") -> None:
    """봇이 의뢰 안내 게시물을 올린 뒤, 해당 포스트 ID를 mid_state에 기록한다."""
    mid = state.noncombat.daily_quest_mid.get(acct)
    if mid is not None:
        mid.bot_reply_post_id = post_id


def handle_daily_quest_roll(acct: str, stat_name: str, state: "BotState") -> str:
    """일일 의뢰 판정 답글 → 굴림 결과 + 1G 지급 + 스프레드시트 업데이트."""
    if stat_name not in NON_COMBAT_STATS:
        return (
            f"◊ 알 수 없는 스탯입니다. 사용 가능한 스탯: {'·'.join(NON_COMBAT_STATS)}"
        )

    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다."

    mid = state.noncombat.daily_quest_mid.get(acct)
    if mid is None:
        return "◊ 진행 중인 의뢰가 없습니다."

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
        result_messages = load_daily_quest_result_messages(state.spreadsheet)
        pool = [m for m in result_messages if m.success_type == success_type]
        judgment = random.choice(pool).message if pool else success_type.value
    except Exception:
        judgment = success_type.value

    new_gold = char_data.gold + 1
    today = date.today().isoformat()

    errors: list[str] = []
    save_succeeded = True
    try:
        update_character_gold_and_quest_date(
            state.spreadsheet, char_data.name, new_gold, today
        )
        updated = replace(char_data, gold=new_gold, daily_quest_date=today)
        state.noncombat_char_dict[acct] = updated
    except Exception as e:
        save_succeeded = False
        errors.append(f"스프레드시트 저장 실패: {e}")

    # 저장에 실패하면 mid 상태를 남겨 두어 같은 게시물에 재시도할 수 있게 한다.
    if save_succeeded:
        del state.noncombat.daily_quest_mid[acct]

    result = f"[{stat_name}] {dice}+{stat_val} → 「{total}」\n{judgment}\n"
    if save_succeeded:
        result += "의뢰를 완수했다. 사례로 1G를 획득했다."
    else:
        result += "의뢰 결과 저장에 실패했습니다. 이 답글에 다시 답글로 재시도해 주세요."
    if errors:
        result += "\n◊ " + "; ".join(errors)
    return result


# ---------------------------------------------------------------------------
# 상시조사
# ---------------------------------------------------------------------------


def handle_investigation_start(acct: str, state: "BotState") -> str:
    """[상시조사] → 현위치 시트를 읽어 4개 선택지 메뉴 반환."""
    nc = state.noncombat

    if nc.investigation_accepted.get(acct):
        return "◊ 이번 구간에서 이미 의뢰를 수주했습니다."

    try:
        location, investigation_active, venues, venue_desc = (
            load_location_and_investigation(state.spreadsheet)
        )
    except Exception as e:
        return f"◊ 조사 정보를 불러오는 중 오류가 발생했습니다: {e}"

    if not investigation_active or not venues:
        return "◊ 현재 상시조사를 진행할 수 없는 구간입니다."

    try:
        general_quests = load_general_quests(state.spreadsheet)
    except Exception as e:
        return f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"

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
    return "\n".join(lines)


def finalize_investigation_menu_post(
    acct: str, post_id: int, state: "BotState"
) -> None:
    state.noncombat.investigation_menu_post_id[acct] = post_id


def handle_investigation_venue_choice(
    acct: str, venue_name: str, state: "BotState"
) -> str:
    """장소 선택 → 일반 의뢰 시트를 읽어 개요 반환."""
    nc = state.noncombat

    quest_id = nc.investigation_venue_to_quest.get(venue_name)
    if quest_id is None:
        # 이 답글은 유효한 의뢰 개요가 아니므로, 이전에 선택했던 의뢰가 남아 있다면
        # 지워 [수락] 시 엉뚱한(예전) 의뢰가 수주되는 것을 방지한다.
        nc.investigation_acct_to_quest_id.pop(acct, None)
        if "자율 탐사" in venue_name or venue_name == FREE_EXPLORE_LABEL:
            return "자유롭게 일대를 돌아다니며 정보를 수집할 수 있습니다."
        return f"◊ '{venue_name}'은(는) 이번 조사의 장소가 아닙니다."

    try:
        general_quests = load_general_quests(state.spreadsheet)
    except Exception as e:
        nc.investigation_acct_to_quest_id.pop(acct, None)
        return f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"

    quest_dict = {q.id: q for q in general_quests}
    quest = quest_dict.get(quest_id)
    if quest is None:
        nc.investigation_acct_to_quest_id.pop(acct, None)
        return "◊ 의뢰 정보를 찾을 수 없습니다."

    existing = nc.quest_status.get(quest_id)
    if existing and existing.participants:
        nc.investigation_acct_to_quest_id.pop(acct, None)
        desc = nc.investigation_venue_to_desc.get(venue_name, "")
        lines = [f"[{venue_name}]에서는 이미 누군가가 의뢰를 수주했습니다."]
        if desc:
            lines.append(desc)
        lines.append("자율 탐사를 진행할 수 있습니다.")
        return "\n".join(lines)

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
    return "\n".join(lines)


def finalize_investigation_overview_post(
    acct: str, post_id: int, state: "BotState"
) -> None:
    state.noncombat.investigation_overview_post_id[acct] = post_id


def handle_investigation_accept(
    acct: str,
    state: "BotState",
    in_reply_to_id: Optional[int] = None,
) -> str:
    """[수락] → 의뢰 참여자 등록.

    자신의 탐사 흐름이거나, 이미 수락된 의뢰의 개요 게시물에 답글로 합류할 수 있다.
    """
    nc = state.noncombat

    if nc.investigation_accepted.get(acct):
        return "◊ 이번 구간에서 이미 의뢰를 수주했습니다."

    quest_id = nc.investigation_acct_to_quest_id.get(acct)

    # 자신의 탐사 흐름이 없으면 in_reply_to_id로 타인의 의뢰에 합류
    if quest_id is None and in_reply_to_id is not None:
        for qid, status in nc.quest_status.items():
            if status.overview_post_id == in_reply_to_id:
                quest_id = qid
                break

    if quest_id is None:
        return "◊ 수락할 의뢰가 없습니다. 먼저 [상시조사]로 의뢰를 확인해 주세요."

    # 의뢰 이름을 일반 의뢰 시트에서 실시간 조회
    quest_name = quest_id
    try:
        general_quests = load_general_quests(state.spreadsheet)
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
    return f"◊ 수락 확인. 「{quest_name}」 의뢰를 수주했습니다."
