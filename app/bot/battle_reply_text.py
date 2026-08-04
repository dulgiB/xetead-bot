"""전투 커맨드(이동/공격/스킬/아이템) 처리 결과를 플레이어가 확인할 답글
텍스트로 조립한다.

`BattlefieldContext.results`(커맨드 처리 후 `context.results[before:]`로 얻는
`list[CommandPartProcessResult]`)를 파트(행동) 하나당 하나의
"【헤더】\n본문" 블록으로 변환하고, 여러 파트가 있으면 빈 줄로 이어붙인다.
"""

from typing import TYPE_CHECKING

from battle.core.commands.models import (
    BattleLogEntry,
    BattleLogEntryKind,
    CommandPart,
    CommandPartProcessResult,
)
from battle.objects.define import ActionType, CombatStatType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def format_battle_reply(
    context: "BattlefieldContext",
    caster_id: CharacterId,
    part_results: list[CommandPartProcessResult],
    *,
    show_skill_preview: bool = False,
) -> str:
    """`show_skill_preview=True`이면 SKILL 파트 헤더 아래에 그 스킬의 효과
    설명을 예고 줄로 덧붙인다 (적군 PRE 선언 답글 전용 — 본 전투/DM 전투에서만
    사용된다). 스킬이 아직 공개되지 않았으면(`SkillData.revealed=False`)
    설명 대신 블라인드 문구를 보여준다."""
    blocks = [
        _format_part(context, caster_id, part_result, show_skill_preview)
        for part_result in part_results
    ]
    return "\n\n".join(blocks)


def format_eliminated_characters(eliminated: list[CharacterId]) -> str:
    """라운드 종료 시 체력 0으로 필드에서 제거된 캐릭터 목록을
    "【탈락】\n▹ {이름}" 블록으로 조립한다. 없으면 빈 문자열."""
    if not eliminated:
        return ""
    lines = "\n".join(f"▹ {char_id.name}" for char_id in eliminated)
    return f"【탈락】\n{lines}"


def format_round_end_log_entries(
    context: "BattlefieldContext", entries: list[BattleLogEntry]
) -> str:
    """라운드 종료 시 발동한 버프(DoT/HoT 등)의 결과를 대상 캐릭터별로 묶어
    "【라운드 종료 처리 ▸ {대상}】" 블록으로 조립한다. 해당 라운드에 발동한
    효과가 없으면 빈 문자열을 반환한다."""
    return _format_grouped_entries(context, "라운드 종료 처리", entries)


def format_battle_end_log_entries(
    context: "BattlefieldContext", entries: list[BattleLogEntry]
) -> str:
    """전투 종료 시점에 발동하는 효과(유예된 재앙 등)의 결과를 대상
    캐릭터별로 묶어 "【전투 종료 처리 ▸ {대상}】" 블록으로 조립한다. 발동한
    효과가 없으면 빈 문자열을 반환한다."""
    return _format_grouped_entries(context, "전투 종료 처리", entries)


def _format_grouped_entries(
    context: "BattlefieldContext", header_label: str, entries: list[BattleLogEntry]
) -> str:
    if not entries:
        return ""
    grouped: dict[str, list[BattleLogEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.target_name, []).append(entry)
    blocks = [
        f"【{header_label} ▸ {target_name}】\n"
        + "\n".join(_format_entry(context, entry) for entry in target_entries)
        for target_name, target_entries in grouped.items()
    ]
    return "\n\n".join(blocks)


def format_final_hp_roster(context: "BattlefieldContext") -> str:
    """전투 종료 시 필드에 남아 있는 모든 캐릭터의 최종 체력을
    "▹ {이름} | {현재 체력}/{최대 체력}" 목록으로 조립한다."""
    return "\n".join(
        f"▹ {char_id.name} | {character.status.curr_hp}/{character.status[CombatStatType.MAX_HP]}"
        for char_id, character in context.characters.items()
    )


def _format_part(
    context: "BattlefieldContext",
    caster_id: CharacterId,
    part_result: CommandPartProcessResult,
    show_skill_preview: bool = False,
) -> str:
    part = part_result.expanded_part.original_part
    assert isinstance(part, CommandPart)
    header = _format_header(caster_id, part)

    log_entries = part_result.log_entries
    if part.type_ == ActionType.MOVE:
        # 최상위 [이동] 커맨드는 헤더가 이미 "어디로 이동했는지"를 보여주므로
        # 그 자체를 나타내는 MOVE 종류 로그는 중복이라 제외한다(스킬 효과로서의
        # 이동과 다름). 다만 그 이동이 ON_ENEMY_MOVE 반격 등을 유발했다면
        # extra_log_entries를 통해 다른 종류(DAMAGE 등)의 로그가 함께 실려
        # 있을 수 있으므로 그건 그대로 보여준다.
        log_entries = [e for e in log_entries if e.kind != BattleLogEntryKind.MOVE]

    lines = []
    if show_skill_preview and part.type_ == ActionType.SKILL:
        lines.append(_format_skill_preview(context, part))
    lines.extend(_format_entry(context, entry) for entry in log_entries)

    if not lines:
        return header
    return header + "\n" + "\n".join(lines)


_BLIND_SKILL_TEXT = "[효과 미확인]"


def _format_skill_preview(context: "BattlefieldContext", part: CommandPart) -> str:
    assert part.skill_id is not None
    skill_data = context.get_skill_data_by_id(part.skill_id)
    text = skill_data.description if skill_data.revealed else _BLIND_SKILL_TEXT
    return f"↳ {text}"


def _format_header(caster_id: CharacterId, part: CommandPart) -> str:
    if part.type_ == ActionType.MOVE:
        column = part.targets[0]
        return f"【이동 ▸ {column}열】"
    if part.type_ == ActionType.ATTACK:
        return f"【공격 ▸ {_target_label(part.targets)}】"
    if part.type_ == ActionType.SKILL:
        return f"【{part.skill_id} ▸ {_skill_target_label(caster_id, part.targets)}】"
    if part.type_ == ActionType.USE_ITEM:
        return f"【{part.item_id} ▸ {_skill_target_label(caster_id, part.targets)}】"
    raise ValueError(part.type_)


def _skill_target_label(caster_id: CharacterId, targets: list) -> str:
    # 자가 대상 스킬(SkillTargetRuleSelf)은 사용자가 대상을 입력하지 않아
    # targets가 비어 있다 — 이 경우 시전자 자신의 이름을 보여준다.
    if not targets:
        return caster_id.name
    return _target_label(targets)


def _target_label(targets: list) -> str:
    return ", ".join(_target_name(target) for target in targets)


def _target_name(target: object) -> str:
    if isinstance(target, CharacterId):
        return target.name
    return f"{target}열"  # BattlefieldColumnIndex


def _format_entry(context: "BattlefieldContext", entry: BattleLogEntry) -> str:
    """캐릭터 이름으로 시작하는 결과 줄 하나를 "▹ "로 시작하는 불릿 형태로
    조립한다 — 여러 캐릭터/효과 줄이 나열될 때도 한눈에 구분되게 하기
    위함이다."""
    if entry.kind == BattleLogEntryKind.DAMAGE:
        return _format_damage_or_heal(entry, sign="-")
    if entry.kind == BattleLogEntryKind.HEAL:
        return _format_damage_or_heal(entry, sign="+")
    if entry.kind == BattleLogEntryKind.MOVE:
        target_id = CharacterId(entry.target_name)
        position = context.find_character_position(target_id)
        return f"▹ {entry.target_name} | {position}열로 이동"
    # BUFF_ADD/BUFF_REMOVE/DEBUFF_CLEAR는 이미 build_log_entries()가 만들어 둔
    # result 문자열을 그대로 쓴다.
    return f"▹ {entry.target_name} | {entry.result}"


def _format_damage_or_heal(entry: BattleLogEntry, *, sign: str) -> str:
    # entry.hp_after/max_hp는 이 대미지/회복이 적용된 "그 시점"의 스냅샷이다.
    # 같은 커맨드에서 같은 대상이 여러 번 맞을/회복될 수 있어(효과 2개 이상),
    # context를 여기서 다시 조회하면 전부 최종 HP로 보이게 되므로 쓰면 안 된다.
    if entry.hp_after is None:
        # 대미지로 사망해 전장에서 제거된 경우 등 — 잔여 체력을 보여줄 수 없다.
        line = f"▹ {entry.target_name} | {sign}{entry.value}"
    else:
        line = f"▹ {entry.target_name} | {sign}{entry.value} → {entry.hp_after}/{entry.max_hp}"
    if entry.roll_display:
        line += f"\n↳ {entry.roll_display}"
    return line
