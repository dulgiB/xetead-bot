import logging
import os
import random
import re
import time
import traceback
from datetime import date
from typing import TYPE_CHECKING, Callable, Optional

from battle.objects.define import ItemType, ValueSourceType
from battle.objects.skill.effects import SkillEffectHeal
from spreadsheets.models.noncombat import NON_COMBAT_STATS, NoncombatStatType
from spreadsheets.models.quest import DailyQuestSuccessType
from utils.name_matching import (
    find_matching_key,
    resolve_matching_key,
    whitespace_tolerant_literal,
)

from bot.load_data import (
    get_character_gold,
    load_daily_quest_pools,
    load_daily_quest_result_messages,
    load_general_quest_sheet,
    load_inventory,
    load_item_data,
    load_mysterious_potion_effects,
    update_character_curr_hp,
    update_character_daily_quest_status_id,
    update_character_quest_date,
    update_quest_taken_by,
)
from bot.log_sheets import (
    NoncombatLogInfo,
    append_ledger_row,
    upsert_investigation_session,
)
from bot.noncombat_state import DailyQuestMidState, InvestigationSession

if TYPE_CHECKING:
    from bot.main import BotState

logger = logging.getLogger(__name__)

_RE_ROLL = re.compile(rf"\[{whitespace_tolerant_literal('판정')}\s*/\s*([^]]+)]")
_RE_BARE_BRACKET = re.compile(r"\[([^\]]+)]")
_RE_TRANSFER_ITEM = re.compile(
    rf"\[{whitespace_tolerant_literal('양도')}\s*/\s*([^\]]+)]"
)

# 아이템 목록은 전투 중 [아이템명/...] 형식과 통일하기 위해 비전투 상황에서도
# "사용/" 접두어 없이 인식한다 — 브래킷이 있는 모든 멘션(사담 등 포함)마다
# 아이템 시트를 읽으면 낭비이므로, 등록이 자주 바뀌지 않는 아이템 목록은
# 멘션 단위 SheetCache와 별개로 TTL 캐싱한다(BotState.item_name_cache*).
_ITEM_NAME_CACHE_TTL_SEC = 300

# "수상한 물약"이 뽑은 효과 텍스트 중 체력 회복을 뜻하는 것만 캐릭터
# 스프레드시트에 반영한다 (예: "체력이 1 회복된다.", "체력이 100 회복된다.").
_RE_MYSTERIOUS_POTION_HEAL_EFFECT = re.compile(r"^체력이 (\d+) 회복된다\.$")
MYSTERIOUS_POTION_ITEM_NAME = "수상한 물약"

# [가방] 목록에서 item_type별로 설명 뒤에 덧붙일 안내 문구. "비전투 소모품"은
# 설명 자체로 비전투 전용임이 자명하므로 별도 문구를 붙이지 않는다. "부적"은
# 뒤가 아니라 설명 앞에 붙는 라벨이라 여기 대신 _BAG_DESCRIPTION_PREFIX에 있다.
_BAG_ITEM_TYPE_SUFFIX: dict[ItemType, str] = {
    ItemType.CONSUMABLE: " 비전투 상황에서도 사용 가능.",
}

# [가방] 목록에서 item_type별로 설명 앞에 붙일 라벨.
_BAG_DESCRIPTION_PREFIX: dict[ItemType, str] = {
    ItemType.CHARM: "부적. ",
}

# "기타"/"비전투 소모품"/"부적"은 코스트·사거리가 항상 0이므로 [가방]에서
# 생략한다.
_BAG_ITEM_TYPES_WITHOUT_COST_RANGE = (
    ItemType.ETC,
    ItemType.NONCOMBAT_CONSUMABLE,
    ItemType.CHARM,
)

# "소모품"은 target_rule에 따라 "(개체/1 · 코스트 N · 사거리 M)"처럼 대상
# 표기를 코스트/사거리와 함께 한 덩어리로 붙인다.
_ITEM_TARGET_RULE_LABELS: dict[str, str] = {
    "SkillTargetRuleSelf": "자신",
    "SkillTargetRuleNamed": "개체/1",
    "SkillTargetRuleNamedWithColumn": "개체+열/1",
    "SkillTargetRuleColumn": "열/1",
    "SkillTargetRuleAllyColumn": "열/1",
}

FREE_EXPLORE_LABEL = "그 외의 장소를 찾아본다."

# main.py와 별개로 읽는다 — bot.main이 이 모듈을 import하므로(순환 import),
# 여기서 bot.main.ADMIN_MASTODON_ID를 직접 가져올 수 없다.
# 상시조사에서 수동 진행으로 인계할 때는 admin이 아니라 세계관 서술을
# 담당하는 별도 계정(WORLD_MASTODON_ID)을 태그한다.
WORLD_MASTODON_ID: str = os.environ["WORLD_MASTODON_ID"]


def parse_stat_name(text: str) -> Optional[str]:
    """텍스트에서 [판정/스탯] 패턴을 찾아 스탯 이름을 반환한다."""
    m = _RE_ROLL.search(text)
    return m.group(1).strip() if m else None


def get_cached_item_names(state: "BotState") -> frozenset[str]:
    """등록된 아이템 id 목록을 TTL 캐싱해 반환한다.

    브래킷이 있는 멘션마다 아이템 시트를 새로 읽지 않도록, 멘션마다 갱신되는
    SheetCache와 별개로 state에 직접 캐싱해 둔다(만료 전까지는 여러 멘션에
    걸쳐 재사용됨).
    """
    now = time.monotonic()
    if (
        state.item_name_cache is None
        or now - state.item_name_cache_loaded_at > _ITEM_NAME_CACHE_TTL_SEC
    ):
        item_dict = load_item_data(state.spreadsheet, cache=state.sheet_cache)
        state.item_name_cache = frozenset(item_dict.keys())
        state.item_name_cache_loaded_at = now
    return state.item_name_cache


def parse_bare_item_command(
    text: str, state: "BotState"
) -> Optional[tuple[str, Optional[str], int]]:
    """텍스트에서 [아이템명(/대상)(/개수)] 패턴을 찾아 (등록된 표기의 아이템명,
    대상 또는 None, 개수)를 반환한다. 전투 중과 동일하게 "사용/" 같은 접두어
    없이 아이템명으로 바로 시작한다 — 첫 토큰이 실제 등록된 아이템명과
    일치할 때만 아이템 사용으로 인식하고, 그 외 대괄호 텍스트(다른 커맨드,
    사담 등)는 조용히 무시한다(아이템명이 다른 커맨드 키워드와 겹치지
    않는다는 전제).
    """
    m = _RE_BARE_BRACKET.search(text)
    if not m:
        return None
    item_name, target, count = _parse_item_args(m.group(1))
    if not item_name:
        return None
    resolved_name = find_matching_key(item_name, get_cached_item_names(state))
    if resolved_name is None:
        return None
    return resolved_name, target, count


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
    reply = f"◊ 판정: {stat_val}[{stat_name}] + {dice}[1d6] → 「{total}」"
    return reply, NoncombatLogInfo(
        command_text=command_text,
        dice_roll=f"{dice}+{stat_val}",
        result=f"「{total}」",
    )


def handle_1d100(
    acct: str, state: "BotState"
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[1D100] → 1~100 사이의 굴림 결과를 반환한다."""
    command_text = "[1D100]"
    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    roll = random.randint(1, 100)
    reply = f"◊ 1d100 → 「{roll}」"
    return reply, NoncombatLogInfo(
        command_text=command_text, dice_roll=str(roll), result=f"「{roll}」"
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


def _format_noncombat_result_line(
    target_name: str, delta: int, current_value: int, max_value: int
) -> str:
    """전투 중 결과 표시(battle_reply_text.py의 merge_damage_heal_lines가 만드는
    "▹ 대상 | ±값 → 현재/최대")와 동일한 형식으로 한 줄을 만든다. 회복/피해 등
    효과 종류별로 문구를 새로 짓지 않고 이 한 형식만 재사용한다.
    """
    sign = "+" if delta >= 0 else ""
    return f"▹ {target_name} | {sign}{delta} → {current_value}/{max_value}"


def handle_use_item(
    acct: str,
    item_name: str,
    target_name: Optional[str],
    count: int,
    state: "BotState",
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[아이템명(/대상)(/개수)] → 비전투 상황에서 즉시 아이템 효과를 적용한다.
    전투 중과 동일하게 "사용/" 같은 접두어 없이 아이템명으로 바로 시작한다.

    "소모품"(item_type)은 전투용 스테이터스를 그대로 재사용해 회복(Heal) 효과만
    지원한다. "비전투 소모품"은 effect가 없고 자신만을 대상으로 아이템별
    전용 로직(_NONCOMBAT_ITEM_HANDLERS)으로 처리된다.
    """
    command_text = (
        f"[{item_name}" + (f"/{target_name}" if target_name else "") + f"/{count}개]"
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
        msg = "◊ 등록되지 않은 아이템입니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)
    if item.item_type not in (ItemType.CONSUMABLE, ItemType.NONCOMBAT_CONSUMABLE):
        msg = "◊ 사용할 수 없는 아이템입니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    if item.item_type == ItemType.NONCOMBAT_CONSUMABLE:
        resolved_target = resolve_matching_key(target_char_name, state.name_dict.keys())
        if resolved_target != user_name:
            msg = "◊ 자신에게만 사용할 수 있는 아이템입니다."
            return msg, NoncombatLogInfo(command_text=command_text, result=msg)
        # 아직 전용 로직이 구현되지 않은 비전투 소모품은, 플레이어 입장에서는
        # 등록되지 않은 아이템과 다를 바 없다 — "구현 예정" 같은 내부 사정을
        # 노출하지 않고 동일한 메시지로 거절한다. 소비 전에 확인해야
        # 존재하지 않는 효과를 위해 아이템이 조용히 사라지는 일이 없다.
        if item_name not in _NONCOMBAT_ITEM_HANDLERS:
            msg = "◊ 등록되지 않은 아이템입니다."
            return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    owned = inventory.get_count(user_name, item_name)
    if owned < count:
        msg = f"◊ 보유한 「{item_name}」의 수가 부족합니다. (현재 {owned}개)"
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    if item.item_type == ItemType.NONCOMBAT_CONSUMABLE:
        try:
            inventory.consume(user_name, item_name, count)
        except Exception as e:
            msg = f"◊ 아이템 사용 처리 중 오류가 발생했습니다: {e}"
            return msg, NoncombatLogInfo(
                command_text=command_text,
                result=msg,
                error_trace=traceback.format_exc(),
            )
        return _NONCOMBAT_ITEM_HANDLERS[item_name](
            user_name, count, state, command_text
        )

    if not isinstance(item.effect, SkillEffectHeal):
        msg = f"◊ '{item_name}'은(는) 비전투 상황에서 지원하지 않는 효과입니다. (회복 아이템만 사용 가능)"
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

    result_line = _format_noncombat_result_line(
        target_char_name, heal_amount, new_hp, target_data.max_hp
    )
    reply = f"◊ {item_name} {count}개를 사용했습니다.\n\n{result_line}"
    return reply, NoncombatLogInfo(
        command_text=command_text,
        dice_roll=f"{item.effect.value_source.value}×{count}",
        result=result_line,
    )


_MYSTERIOUS_POTION_EFFECT_JOINER = " 그리고…… "


def _handle_mysterious_potion(
    user_name: str, count: int, state: "BotState", command_text: str
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """ "수상한 물약" 사용 → "수상한 효과" 시트에서 무작위 효과 텍스트를
    count개 뽑아(중복 허용) " 그리고…… "로 이어붙여 답글로 낸다. 체력
    회복을 뜻하는 텍스트("체력이 N 회복된다.")가 여러 개 뽑히면 회복량을
    합산해 캐릭터 스프레드시트에 한 번만 반영한다.
    """
    try:
        effects = load_mysterious_potion_effects(
            state.spreadsheet, cache=state.sheet_cache
        )
    except Exception as e:
        msg = f"◊ 수상한 효과 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )
    if not effects:
        msg = "◊ '수상한 물약'의 효과 목록이 비어 있습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    effect_texts = random.choices(effects, k=count)
    combined_effects = _MYSTERIOUS_POTION_EFFECT_JOINER.join(effect_texts)
    first_line = f"수상한 물약을 마셨다. ……어라? {combined_effects}"
    lines = [first_line]

    total_heal = sum(
        int(heal_match.group(1))
        for heal_match in (
            _RE_MYSTERIOUS_POTION_HEAL_EFFECT.match(text) for text in effect_texts
        )
        if heal_match is not None
    )
    target_data = state.name_dict.get(user_name)
    if total_heal > 0 and target_data is not None:
        prev_hp = target_data.curr_hp or 0
        new_hp = min(target_data.max_hp, prev_hp + total_heal)
        try:
            update_character_curr_hp(
                state.spreadsheet, user_name, new_hp, cache=state.sheet_cache
            )
            lines[0] += f" ({new_hp}/{target_data.max_hp})"
        except Exception as e:
            lines.append(f"◊ 체력 반영 중 오류가 발생했습니다: {e}")

    lines += [
        "",
        "◊ 효과는 자정 혹은 스토리 진행 전까지 지속됩니다. 기존에 진행 중이던 대화에는 반영되지 않습니다.",
    ]
    reply = "\n".join(lines)
    return reply, NoncombatLogInfo(command_text=command_text, result=combined_effects)


# item_type="비전투 소모품"인 아이템명 → 전용 처리 함수. handle_use_item이
# 아이템명이 이 dict에 없으면 소비 전에 "등록되지 않은 아이템입니다."로
# 거절한다 — 플레이어 입장에서는 미구현도 미등록과 다를 바 없어야 하고,
# 어차피 처리할 방법이 없는 아이템을 소비해 버리면 안 되기 때문이다.
_NONCOMBAT_ITEM_HANDLERS: dict[
    str, Callable[[str, int, "BotState", str], tuple[str, Optional[NoncombatLogInfo]]]
] = {
    MYSTERIOUS_POTION_ITEM_NAME: _handle_mysterious_potion,
}


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
        msg = "◊ 등록되지 않은 아이템입니다."
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


def handle_bag(acct: str, state: "BotState") -> tuple[str, Optional[NoncombatLogInfo]]:
    """[가방] → 소지금과 보유 아이템 목록을 출력한다. 어떤 맥락에서도 사용 가능."""
    command_text = "[가방]"
    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return "◊ 등록된 캐릭터를 찾을 수 없습니다.", None

    try:
        item_dict = load_item_data(state.spreadsheet, cache=state.sheet_cache)
        inventory = load_inventory(state.spreadsheet, cache=state.sheet_cache)
    except Exception as e:
        msg = f"◊ 소지품 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    owned = inventory.items_for_character(char_data.name)
    lines = [f"◊ {char_data.name}의 소지품", "", f"▹ 소지금: {char_data.gold}G"]
    for item_name, count in owned.items():
        item = item_dict.get(item_name)
        if item is None:
            lines.append(f"▹ {item_name}×{count}: (아이템 정보를 찾을 수 없습니다)")
            continue
        usable_suffix = _BAG_ITEM_TYPE_SUFFIX.get(item.item_type, "")
        description_prefix = _BAG_DESCRIPTION_PREFIX.get(item.item_type, "")

        info_parts = []
        if item.item_type == ItemType.CONSUMABLE:
            target_label = _ITEM_TARGET_RULE_LABELS.get(
                item.target_rule, item.target_rule
            )
            info_parts.append(target_label)
        if item.item_type not in _BAG_ITEM_TYPES_WITHOUT_COST_RANGE:
            info_parts.append(f"코스트 {item.cost}")
            info_parts.append(f"사거리 {item.attack_range}")
        info_prefix = f"({' · '.join(info_parts)}) " if info_parts else ""

        lines.append(
            f"▹ {item_name}×{count}: {info_prefix}{description_prefix}"
            f"{item.description}{usable_suffix}"
        )

    reply = "\n".join(lines)
    return reply, NoncombatLogInfo(
        command_text=command_text, result=f"소지품 조회: {char_data.name}"
    )


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
        msg = "오늘은 이미 의뢰 하나를 해결했다. 의욕 넘치는 모험가에게도 휴식은 필요한 법이니 이만 쉬도록 하자."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        pools = load_daily_quest_pools(state.spreadsheet, cache=state.sheet_cache)
    except Exception as e:
        msg = f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    if not (pools.client_categories and pools.client_names and pools.quest_contents):
        msg = "◊ 현재 받을 수 있는 의뢰가 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    client_category = random.choice(pools.client_categories)
    client_name = random.choice(pools.client_names)
    quest_content = random.choice(pools.quest_contents)

    state.noncombat.daily_quest_mid[acct] = DailyQuestMidState(bot_reply_post_id=0)

    reply = (
        f"{client_category} {client_name} {quest_content}. 어떻게 할까?\n"
        "\n◊ [판정/(육체·지식·인간·마법·기술 중 택1)] 형식으로 답글을 달아 의뢰를 수행할 수 있습니다."
    )
    return reply, NoncombatLogInfo(
        command_text=command_text,
        result=f"의뢰 배정: {client_category} {client_name} {quest_content}",
    )


def finalize_daily_quest_mid(acct: str, post_id: int, state: "BotState") -> None:
    """봇이 의뢰 안내 게시물을 올린 뒤, 해당 포스트 ID를 mid_state에 기록한다.

    스프레드시트에도 함께 기록해 둔다 — 봇이 재기동되면 인메모리 mid_state는
    사라지지만(main()의 재기동 복원이 대상으로 삼지 않음), 이 판정 대기
    포스트 ID를 캐릭터 시트에서 다시 읽어 복원할 수 있다. 저장에 실패해도
    사용자에게는 이미 의뢰 안내 게시물이 정상적으로 전달된 뒤라 진행 자체를
    막지 않는다 — 재기동 복원만 안 될 뿐, 지금 이 프로세스가 살아있는 동안은
    인메모리 mid_state로 정상 진행된다.
    """
    mid = state.noncombat.daily_quest_mid.get(acct)
    if mid is None:
        return
    mid.bot_reply_post_id = post_id

    char_data = state.noncombat_char_dict.get(acct)
    if char_data is None:
        return
    try:
        update_character_daily_quest_status_id(
            state.spreadsheet, char_data.name, str(post_id), cache=state.sheet_cache
        )
    except Exception:
        logger.exception("일일 의뢰 진행 상태 저장 실패(재기동 복원용)")


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

    # 캐릭터 시트의 gold는 더 이상 봇이 직접 갱신하지 않는다 — 소지금 변동은
    # "가계부" 시트 기록만으로 관리하고, gold는 그 내역을 근거로 한 스프레드
    # 시트 수식이 계산한다. new_gold는 가계부 기록/재조회가 실패했을 때만
    # 쓰이는 예상치(로컬 계산)로, 정상 경로에서는 아래에서 실제 값으로
    # 덮어써진다.
    new_gold = char_data.gold + 1
    today = date.today().isoformat()

    errors: list[str] = []
    save_succeeded = True
    save_error_trace: Optional[str] = None
    try:
        update_character_quest_date(
            state.spreadsheet, char_data.name, today, cache=state.sheet_cache
        )
    except Exception as e:
        save_succeeded = False
        save_error_trace = traceback.format_exc()
        errors.append(f"스프레드시트 저장 실패: {e}")

    # 저장에 실패하면 mid 상태를 남겨 두어 같은 게시물에 재시도할 수 있게 한다.
    if save_succeeded:
        del state.noncombat.daily_quest_mid[acct]
        ledger_appended = False
        try:
            append_ledger_row(
                state.spreadsheet,
                today,
                char_data.name,
                "일일 의뢰",
                1,
                cache=state.sheet_cache,
            )
            ledger_appended = True
        except Exception:
            logger.exception("가계부 기록 실패")

        if ledger_appended:
            # gold 수식이 방금 추가한 가계부 행을 반영한 값을 다시 읽는다 —
            # char_data.gold + 1로 로컬 계산하면 가계부에 이미 있던 다른
            # 변동(수동 지급 등)을 놓친다.
            try:
                if state.sheet_cache is not None:
                    state.sheet_cache.invalidate("캐릭터")
                new_gold = get_character_gold(
                    state.spreadsheet, char_data.name, cache=state.sheet_cache
                )
            except Exception:
                logger.exception("소지금 재조회 실패")

    result = (
        f"◊ 판정: {stat_val}[{stat_name}] + {dice}[1d6] → 「{total}」\n{judgment}\n"
    )
    if save_succeeded:
        result += f"\n의뢰를 완수했다. 사례로 1G를 획득했다. (소지금: {new_gold}G)"
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
    """[상시조사] → '일반 의뢰' 시트의 활성 장소를 읽어 선택지 메뉴 반환."""
    command_text = "[상시조사]"

    try:
        location, quests = load_general_quest_sheet(
            state.spreadsheet, cache=state.sheet_cache
        )
    except Exception as e:
        msg = f"◊ 조사 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    if location is None or not quests:
        msg = "◊ 현재 상시조사를 진행할 수 없는 구간입니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    lines = [location.description_quest]
    for quest in quests:
        lines.append(f"▸ [{quest.location}]")
    lines.append(f"▸ {FREE_EXPLORE_LABEL} (자율 탐사)")
    reply = "\n".join(lines)
    return reply, NoncombatLogInfo(
        command_text=command_text,
        result=f"메뉴 제공: {', '.join(q.location for q in quests)}",
    )


def finalize_investigation_menu_post(
    acct: str, post_id: int, state: "BotState"
) -> InvestigationSession:
    """새 상시조사 메뉴 게시물로 세션을 (재)시작한다. 그 acct에 이미 진행
    중인 세션이 있으면(끝맺지 않고 다시 [상시조사]를 보낸 경우) 먼저
    종료 처리해 시트에 반영한다."""
    nc = state.noncombat
    prior = nc.investigations.get(acct)
    if prior is not None and not prior.ended:
        prior.ended = True
        upsert_investigation_session(state.spreadsheet, prior, cache=state.sheet_cache)

    session = InvestigationSession(
        field_id=str(post_id), acct=acct, menu_post_id=post_id
    )
    nc.investigations[acct] = session
    upsert_investigation_session(state.spreadsheet, session, cache=state.sheet_cache)
    return session


def handle_investigation_menu_idle_reply(
    session: InvestigationSession, state: "BotState"
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[상시조사] 메뉴 게시물에 [장소명] 없이(사담 등) 직속 답글이 달리면
    → 자율적으로 주변을 둘러본 것으로 안내하고, GM이 이어서 서술할 수
    있도록 world 계정을 태그한다. world가 태그되는 순간이므로 세션은
    여기서 종료된다."""
    command_text = "(상시조사 메뉴 답글, 장소 미지정)"
    session.ended = True
    upsert_investigation_session(state.spreadsheet, session, cache=state.sheet_cache)
    msg = f"원하는 곳을 둘러보기로 했다. @{WORLD_MASTODON_ID}"
    return msg, NoncombatLogInfo(command_text=command_text, result="장소 미지정")


def handle_investigation_venue_choice(
    session: InvestigationSession, venue_name: str, state: "BotState"
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """장소 선택 → '일반 의뢰' 시트를 읽어 개요 반환."""
    command_text = f"[상시조사/{venue_name}]"

    try:
        location, quests = load_general_quest_sheet(
            state.spreadsheet, cache=state.sheet_cache
        )
    except Exception as e:
        msg = f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    if location is None or not quests:
        msg = "◊ 등록되지 않은 장소입니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    venue_lookup = {q.location: q for q in quests}
    matched_venue = resolve_matching_key(venue_name, venue_lookup.keys())
    quest = venue_lookup.get(matched_venue)
    if quest is None:
        if "자율 탐사" in venue_name or venue_name == FREE_EXPLORE_LABEL:
            session.ended = True
            upsert_investigation_session(
                state.spreadsheet, session, cache=state.sheet_cache
            )
            msg = (
                "다른 곳에 가보기로 했다. 자유롭게 일대를 돌아다니며 "
                f"정보를 수집할 수 있다. @{WORLD_MASTODON_ID}"
            )
            return msg, NoncombatLogInfo(command_text=command_text, result=msg)
        # 이 답글은 유효한 의뢰 개요가 아니다 — 이전에 선택했던 quest_id가
        # 남아 있으면, 뒤이어 finalize_investigation_overview_post가 이
        # (틀린) 답글을 그 옛 의뢰의 개요인 것처럼 등록해 [수락] 시 엉뚱한
        # 의뢰가 수주되는 것을 방지하기 위해 지운다.
        session.quest_id = None
        msg = "◊ 등록되지 않은 장소입니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    session.quest_id = quest.id
    upsert_investigation_session(state.spreadsheet, session, cache=state.sheet_cache)

    if quest.taken_by_list():
        lines = [
            f"[{quest.location}](으)로 이동했다.",
            "",
            quest.current_description(),
            "",
            "◊ 이 장소의 의뢰는 이미 누군가에 의해 수주되었습니다. 커맨드가 없는 "
            "답글을 보내 자율 탐사를 시작하거나, 커맨드를 입력해 다른 장소로 "
            "이동할 수 있습니다.",
        ]
        reply = "\n".join(lines)
        return reply, NoncombatLogInfo(
            command_text=command_text, result=f"이미 수주된 의뢰 안내: {quest.name}"
        )

    reward_desc = quest.reward if quest.reward else "미정"
    lines = [
        f"[{quest.location}](으)로 이동했다.",
        "",
        quest.current_description(),
        "",
        f"**[일반 의뢰] {quest.name}**",
        f"▸ 계열: {quest.type} - {quest.subtype}",
        f"▸ 클리어 가능 기간: {quest.available_until}",
        f"▸ 보상: {reward_desc}",
        "",
        "이 의뢰를 수락할까?",
        "",
        "◊ 의뢰를 받으려면 답글로 의뢰에 참여할 인원 전원을 멘션하면서 [수락]을 "
        "입력해 주세요. 의뢰를 받는 대신 이 장소에서 자율 탐사를 진행하려면 "
        "키워드가 없는 답글을 보내 주세요.",
    ]
    reply = "\n".join(lines)
    return reply, NoncombatLogInfo(
        command_text=command_text, result=f"의뢰 개요 제공: {quest.name}"
    )


def finalize_investigation_overview_post(
    session: InvestigationSession, post_id: int, state: "BotState"
) -> None:
    """의뢰 개요 답글이 실제로 게시된 뒤, 그 게시물 id를 세션에 기록한다.

    handle_investigation_venue_choice가 유효한 의뢰를 찾지 못했거나(장소
    오류) 자율 탐사로 세션을 이미 종료한 경우엔 session.quest_id가 비어
    있으므로 아무 것도 하지 않는다."""
    if session.quest_id is None:
        return
    session.overview_post_id = post_id
    upsert_investigation_session(state.spreadsheet, session, cache=state.sheet_cache)


def handle_investigation_accept(
    session: InvestigationSession,
    mentions: list[str],
    state: "BotState",
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """[수락] → 답글에 멘션된 인원 전원(+ 발신자)을 참여자로 등록하고 '일반
    의뢰' 시트의 taken_by에 기록한다.

    같은 장소의 의뢰 3개(운반/탐사/전투)는 서로 다른 인원이 각각 독립적으로
    수주할 수 있다 — 다만 한 캐릭터가 그중 이미 하나를 수주한 채 다른 의뢰를
    또 수주할 수는 없다(taken_by 기준으로 확인).
    """
    command_text = "[수락]"
    acct = session.acct
    quest_id = session.quest_id
    if quest_id is None:
        msg = "◊ 수락할 의뢰가 없습니다. 먼저 [상시조사]로 의뢰를 확인해 주세요."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        _, quests = load_general_quest_sheet(state.spreadsheet, cache=state.sheet_cache)
    except Exception as e:
        msg = f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    quest = next((q for q in quests if q.id == quest_id), None)
    if quest is None:
        msg = "◊ 의뢰 정보를 찾을 수 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    if quest.taken_by_list():
        msg = "◊ 이미 다른 인원이 수주한 의뢰입니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    participants = [acct] + [m for m in mentions if m != acct]

    already_busy = {a for q in quests for a in q.taken_by_list()}
    conflicts = [p for p in participants if p in already_busy]
    if conflicts:
        msg = (
            "◊ 이미 다른 의뢰를 수주한 캐릭터가 있어 수락할 수 없습니다: "
            + ", ".join(f"@{c}" for c in conflicts)
        )
        return msg, NoncombatLogInfo(
            command_text=command_text, result=f"수주 중복: {', '.join(conflicts)}"
        )

    try:
        update_quest_taken_by(
            state.spreadsheet, quest_id, ",".join(participants), cache=state.sheet_cache
        )
    except Exception as e:
        msg = f"◊ 의뢰 수주 처리 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    session.ended = True
    upsert_investigation_session(state.spreadsheet, session, cache=state.sheet_cache)

    reply = (
        f"「{quest.name}」 의뢰를 받았다!\n\n"
        f"◊ 의뢰를 수락했습니다. 이후는 수동으로 진행됩니다. @{WORLD_MASTODON_ID}"
    )
    return reply, NoncombatLogInfo(
        command_text=command_text,
        result=f"의뢰 수주: {quest.name} ({', '.join(participants)})",
    )


def handle_investigation_decline(
    session: InvestigationSession,
    state: "BotState",
) -> tuple[str, Optional[NoncombatLogInfo]]:
    """의뢰 개요 게시물에 [수락]도 다른 인식 가능한 커맨드도 아닌 답글이
    달리면 → 의뢰를 받지 않고 자리를 떠난 것으로 안내하고, GM이 이어서
    서술할 수 있도록 world를 태그한다. world가 태그되는 순간이므로 세션은
    여기서 종료된다."""
    command_text = "(의뢰 개요 답글, 미수락)"
    quest_id = session.quest_id
    if quest_id is None:
        msg = "◊ 의뢰 정보를 찾을 수 없습니다."
        return msg, NoncombatLogInfo(command_text=command_text, result=msg)

    try:
        _, quests = load_general_quest_sheet(state.spreadsheet, cache=state.sheet_cache)
    except Exception as e:
        msg = f"◊ 의뢰 정보를 불러오는 중 오류가 발생했습니다: {e}"
        return msg, NoncombatLogInfo(
            command_text=command_text, result=msg, error_trace=traceback.format_exc()
        )

    quest = next((q for q in quests if q.id == quest_id), None)
    location = quest.location if quest else ""

    session.ended = True
    upsert_investigation_session(state.spreadsheet, session, cache=state.sheet_cache)

    msg = (
        f"의뢰는 수락하지 않고 {location} 일대를 둘러보기로 했다. @{WORLD_MASTODON_ID}"
    )
    return msg, NoncombatLogInfo(command_text=command_text, result="의뢰 미수락")
