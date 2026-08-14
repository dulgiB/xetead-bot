"""전투 커맨드(이동/공격/스킬/아이템) 처리 결과를 플레이어가 확인할 답글
텍스트로 조립한다.

`BattlefieldContext.results`(커맨드 처리 후 `context.results[before:]`로 얻는
`list[CommandPartProcessResult]`)를 헤더 없이 "▹ 대상 | 결과" 줄만으로
조립하고, 여러 파트의 결과 줄을 그대로 이어붙인다(파트 사이 구분 없음) —
어떤 커맨드/스킬이었는지보다 최종 결과만 한눈에 보여주는 요약이 목적이다.

계산식(주사위/계수 등)은 본문과 분리해서 반환한다 — 답글이 길어지는 주범이라
호출측(봇 인터페이스)이 본문을 CW(content warning) 게시물의 spoiler_text로,
계산식을 그 게시물의 (접힌) 본문으로 넣어 게시물 하나로 합치거나(개별 커맨드
답글), 본문+이미지를 먼저 올리고 계산식만 별도의 CW 후속 게시물로 이어
붙인다(적 후행 정산·라운드/전투 종료 처리 등 이미지가 함께 붙는 집계용
게시물). 계산식은 파트(행동)별로 "【헤더】" 블록으로 묶여 어떤 커맨드의
계산인지 알 수 있다. 계산식 줄 끝에는 그 계산이 만들어낸 최종 값을
"→ 값" 형태로 덧붙여, 계산식만 펼쳐 봐도 결과를 바로 알 수 있게 한다.
"""

from typing import TYPE_CHECKING, Optional

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
    from battle.objects.character.combat_character import CombatCharacter


def format_battle_reply(
    context: "BattlefieldContext",
    caster_id: CharacterId,
    part_results: list[CommandPartProcessResult],
    *,
    show_skill_preview: bool = False,
) -> tuple[str, str]:
    """(본문, 계산식) 튜플을 반환한다. 표시할 계산식이 없으면 두 번째 값은
    빈 문자열이다.

    본문(spoiler_text로 항상 바로 보이는 요약)은 헤더 없이 "▹ 대상 | 결과"
    줄만 파트 구분 없이 이어붙인다 — 어떤 스킬/커맨드였는지보다 최종
    결과만 한눈에 보여주는 편이 낫다는 판단.

    `show_skill_preview=True`이면 SKILL 파트마다 그 스킬의 효과 설명을
    예고 줄로 덧붙인다 (적군 PRE 선언 답글 전용 — 본 전투/DM 전투에서만
    사용된다). 스킬이 아직 공개되지 않았으면(`SkillData.revealed=False`)
    설명 대신 블라인드 문구를 보여준다."""
    bodies = []
    calc_blocks = []
    for part_result in part_results:
        body, calc_block = _format_part(
            context, caster_id, part_result, show_skill_preview
        )
        if body:
            bodies.append(body)
        if calc_block:
            calc_blocks.append(calc_block)
    return "\n".join(bodies), "\n\n".join(calc_blocks)


def format_eliminated_characters(eliminated: list[CharacterId]) -> str:
    """라운드 종료 시 체력 0으로 필드에서 제거된 캐릭터 목록을
    "【탈락】\n▹ {이름}" 블록으로 조립한다. 없으면 빈 문자열."""
    if not eliminated:
        return ""
    lines = "\n".join(f"▹ {char_id.name}" for char_id in eliminated)
    return f"【탈락】\n{lines}"


def format_round_end_log_entries(
    context: "BattlefieldContext", entries: list[BattleLogEntry]
) -> tuple[str, str]:
    """라운드 종료 시 발동한 버프(DoT/HoT 등)의 결과를 대상 캐릭터별로 묶어
    "【라운드 종료 처리 ▸ {대상}】" 블록으로 조립한 (본문, 계산식) 튜플을
    반환한다. 해당 라운드에 발동한 효과가 없으면 둘 다 빈 문자열이다."""
    if not entries:
        return "", ""
    grouped: dict[str, list[BattleLogEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.target_name, []).append(entry)
    body_blocks = []
    calc_blocks = []
    for target_name, target_entries in grouped.items():
        header = f"【라운드 종료 처리 ▸ {target_name}】"
        lines = []
        calc_lines = []
        for entry in target_entries:
            line, calc, final_value = _format_entry(context, entry)
            lines.append(line)
            if calc:
                calc_lines.append(f"▹ {entry.target_name} | {calc} → {final_value}")
        body_blocks.append(f"{header}\n" + "\n".join(lines))
        if calc_lines:
            calc_blocks.append(f"{header}\n" + "\n".join(calc_lines))
    return "\n\n".join(body_blocks), "\n\n".join(calc_blocks)


def format_battle_end_log_entries(
    context: "BattlefieldContext", entries: list[BattleLogEntry]
) -> tuple[str, str]:
    """전투 종료 시점에 발동하는 효과(유예된 재앙 등)의 결과를 "【전투 종료
    처리】" 헤더 하나 아래 모든 대상의 결과를 나열한 (본문, 계산식) 튜플을
    반환한다. 전투 종료 정산은 CW로 접어 두지 않고 한 번에 다 보여주는
    편이 낫다는 판단으로, 계산식도 본문에 함께 포함시키고 두 번째 값은
    항상 빈 문자열이다(호출측이 CW 후속 게시물을 만들지 않도록). 발동한
    효과가 없으면 둘 다 빈 문자열이다."""
    if not entries:
        return "", ""
    lines = []
    for entry in entries:
        line, calc, final_value = _format_entry(context, entry)
        lines.append(line)
        if calc:
            lines.append(f"　↳ {calc} → {final_value}")
    header = "【전투 종료 처리】"
    body = f"{header}\n" + "\n".join(lines)
    calc = ""
    return body, calc


def format_final_hp_roster(context: "BattlefieldContext") -> str:
    """전투 종료 시 필드에 남아 있는 모든 캐릭터의 최종 체력을
    "▹ {이름} | {현재 체력}/{최대 체력}" 목록으로 조립한다. 동료(소환수)는
    맨 아래에 몰아서 나열하는 대신 owner 바로 아래에 "　↳ {이름} | ..."로
    중첩해서 보여준다 — owner가 이미 전장에서 제거되어 없는 예외적인
    경우에만 최상위 "▹" 줄로 보여준다."""
    lines = []
    for char_id, character in context.characters.items():
        owner_id = context.companion_owners.get(char_id)
        if owner_id is not None and owner_id in context.characters:
            continue  # owner 줄을 그릴 때 함께 그린다
        lines.append(_format_roster_line(character, "▹"))
        companion_id = context.find_companion_id(char_id)
        if companion_id is not None and companion_id in context.characters:
            lines.append(_format_roster_line(context.characters[companion_id], "　↳"))
    return "\n".join(lines)


def _format_roster_line(character: "CombatCharacter", bullet: str) -> str:
    curr_hp = character.status.curr_hp
    max_hp = character.status[CombatStatType.MAX_HP]
    return f"{bullet} {character.id.name} | {curr_hp}/{max_hp}"


def _header_and_log_entries(
    caster_id: CharacterId, part_result: CommandPartProcessResult
) -> tuple[CommandPart, str, list[BattleLogEntry]]:
    part = part_result.expanded_part.original_part
    assert isinstance(part, CommandPart)
    header = _format_header(caster_id, part)
    return part, header, part_result.log_entries


def _format_part(
    context: "BattlefieldContext",
    caster_id: CharacterId,
    part_result: CommandPartProcessResult,
    show_skill_preview: bool = False,
) -> tuple[str, str]:
    part, header, log_entries = _header_and_log_entries(caster_id, part_result)

    body_lines = []
    if show_skill_preview and part.type_ == ActionType.SKILL:
        body_lines.append(_format_skill_preview(context, part))

    calc_lines = []
    for entry in log_entries:
        line, calc, final_value = _format_entry(context, entry)
        body_lines.append(line)
        if calc:
            calc_lines.append(f"▹ {entry.target_name} | {calc} → {final_value}")

    # 적 후행 정산으로 미뤄지는 공격 등, 이 시점엔 아직 아무 결과도 없는
    # 파트(예: PRE 선언)는 보여줄 결과 줄이 없다 — 그래도 커맨드가
    # 접수됐다는 확인 자체는 필요하므로 이때만 예외적으로 헤더로 대체한다.
    body = "\n".join(body_lines) if body_lines else header
    calc_block = f"{header}\n" + "\n".join(calc_lines) if calc_lines else ""
    return body, calc_block


_BLIND_SKILL_TEXT = "[효과 미확인]"


def _format_skill_preview(context: "BattlefieldContext", part: CommandPart) -> str:
    assert part.skill_id is not None
    skill_data = context.get_skill_data_by_id(part.skill_id)
    text = skill_data.description if skill_data.revealed else _BLIND_SKILL_TEXT
    return f"　↳ {text}"


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


def _format_entry(
    context: "BattlefieldContext", entry: BattleLogEntry
) -> tuple[str, Optional[str], Optional[str]]:
    """캐릭터 이름으로 시작하는 결과 줄 하나를 "▹ "로 시작하는 불릿 형태로
    조립해 (본문 줄, 계산식 또는 None, 최종 값 표시 또는 None)을 반환한다 —
    여러 캐릭터/효과 줄이 나열될 때도 한눈에 구분되게 하기 위함이다."""
    if entry.kind == BattleLogEntryKind.DAMAGE:
        return _format_damage_or_heal(entry, sign="-")
    if entry.kind == BattleLogEntryKind.HEAL:
        return _format_damage_or_heal(entry, sign="+")
    if entry.kind == BattleLogEntryKind.MOVE:
        target_id = CharacterId(entry.target_name)
        position = context.find_character_position(target_id)
        return f"▹ {entry.target_name} | {position}열로 이동", None, None
    # BUFF_ADD/BUFF_REMOVE/DEBUFF_CLEAR는 이미 build_log_entries()가 만들어 둔
    # result 문자열을 그대로 쓴다.
    return f"▹ {entry.target_name} | {entry.result}", None, None


def _format_damage_or_heal(
    entry: BattleLogEntry, *, sign: str
) -> tuple[str, Optional[str], Optional[str]]:
    # entry.hp_after/max_hp는 이 대미지/회복이 적용된 "그 시점"의 스냅샷이다.
    # 같은 커맨드에서 같은 대상이 여러 번 맞을/회복될 수 있어(효과 2개 이상),
    # context를 여기서 다시 조회하면 전부 최종 HP로 보이게 되므로 쓰면 안 된다.
    final_value = f"{sign}{entry.value}"
    if entry.hp_after is None:
        # 대미지로 사망해 전장에서 제거된 경우 등 — 잔여 체력을 보여줄 수 없다.
        line = f"▹ {entry.target_name} | {final_value}"
    else:
        line = (
            f"▹ {entry.target_name} | {final_value} → {entry.hp_after}/{entry.max_hp}"
        )
    return line, entry.roll_display, final_value
