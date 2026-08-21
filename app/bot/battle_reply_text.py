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
    _merged_lines: Optional[dict[tuple[BattleLogEntryKind, str], str]] = None,
    _emitted: Optional[set[tuple[BattleLogEntryKind, str]]] = None,
) -> tuple[str, str]:
    """(본문, 계산식) 튜플을 반환한다. 표시할 계산식이 없으면 두 번째 값은
    빈 문자열이다.

    본문(spoiler_text로 항상 바로 보이는 요약)은 헤더 없이 "▹ 대상 | 결과"
    줄만 파트 구분 없이 이어붙인다 — 어떤 스킬/커맨드였는지보다 최종
    결과만 한눈에 보여주는 편이 낫다는 판단. 같은 대상의 대미지/회복이
    여러 파트에 걸쳐(예: 공격/대상-공격/대상-공격/대상) 나와도 본문에는
    합산된 한 줄로만 보인다 — 계산식에는 각 파트의 굴림이 그대로 남는다.

    `show_skill_preview=True`이면 SKILL 파트마다 그 스킬의 효과 설명을
    예고 줄로 덧붙인다 (적군 PRE 선언 답글 전용 — 본 전투/DM 전투에서만
    사용된다). 스킬이 아직 공개되지 않았으면(`SkillData.revealed=False`)
    설명 대신 블라인드 문구를 보여준다.

    `_merged_lines`/`_emitted`는 admin.py의 `_format_named_reply()`처럼
    파트를 하나씩 잘라 이 함수를 여러 번 호출하는 프록시 경로 전용이다 —
    그 경로는 파트 전체를 한 번에 못 보므로, 호출측이 전체 파트 기준으로
    미리 계산한 합산 결과를 여기 넘겨 공유해야 여러 번 호출해도 중복
    없이 한 곳에서만 합산된 줄이 나온다. 직접 호출(본 전투/DM 전투/대련의
    캐릭터 커맨드)은 항상 전체 파트 리스트를 한 번에 넘기므로 넘길 필요
    없다(내부에서 자체적으로 계산한다)."""
    parts = drop_intermediate_consecutive_moves(part_results)
    merged_lines = (
        _merged_lines if _merged_lines is not None else merge_damage_heal_lines(parts)
    )
    emitted = _emitted if _emitted is not None else set()

    bodies = []
    calc_blocks = []
    for part_result in parts:
        body, calc_block = _format_part(
            context, caster_id, part_result, show_skill_preview, merged_lines, emitted
        )
        if body:
            bodies.append(body)
        if calc_block:
            calc_blocks.append(calc_block)
    return "\n".join(bodies), "\n\n".join(calc_blocks)


_MERGEABLE_KINDS = (BattleLogEntryKind.DAMAGE, BattleLogEntryKind.HEAL)


def merge_damage_heal_lines(
    part_results: list[CommandPartProcessResult],
) -> dict[tuple[BattleLogEntryKind, str], str]:
    """part_results 전체에 걸쳐 같은 (종류, 대상) 조합의 대미지/회복을
    합산해 "▹ 대상 | ±합계 → hp/max [라벨...]" 한 줄로 미리 조립해 둔다.
    최종 hp_after/max_hp는 등장 순서상 마지막 항목의 값을 쓴다(그 시점이
    실제로 가장 최신 상태이므로). 라벨(entry.source_labels)은 등장 순서를
    유지한 채 파트 전체에 걸쳐 중복 제거해 모은다 — 반격/반사/코모이디아류처럼
    같은 대상이 여러 반응형 버프의 대상이 됐을 때도 라벨이 하나씩만 남는다."""
    totals: dict[tuple[BattleLogEntryKind, str], int] = {}
    last_hp_after: dict[tuple[BattleLogEntryKind, str], Optional[int]] = {}
    last_max_hp: dict[tuple[BattleLogEntryKind, str], Optional[int]] = {}
    labels: dict[tuple[BattleLogEntryKind, str], list[str]] = {}
    for part_result in part_results:
        for entry in part_result.log_entries:
            if entry.kind not in _MERGEABLE_KINDS or entry.value is None:
                continue
            key = (entry.kind, entry.target_name)
            totals[key] = totals.get(key, 0) + entry.value
            last_hp_after[key] = entry.hp_after
            last_max_hp[key] = entry.max_hp
            key_labels = labels.setdefault(key, [])
            for label in entry.source_labels:
                if label not in key_labels:
                    key_labels.append(label)

    lines: dict[tuple[BattleLogEntryKind, str], str] = {}
    for key, total in totals.items():
        _kind, target_name = key
        sign = "-" if key[0] == BattleLogEntryKind.DAMAGE else "+"
        hp_after = last_hp_after[key]
        label_suffix = "".join(f" [{label}]" for label in labels.get(key, []))
        if hp_after is None:
            lines[key] = f"▹ {target_name} | {sign}{total}{label_suffix}"
        else:
            lines[key] = (
                f"▹ {target_name} | {sign}{total} → "
                f"{hp_after}/{last_max_hp[key]}{label_suffix}"
            )
    return lines


def drop_intermediate_consecutive_moves(
    part_results: list[CommandPartProcessResult],
) -> list[CommandPartProcessResult]:
    """연속된 이동 파트(예: 이동/2열-이동/3열-이동/4열)는 경유지를 하나하나
    보여줄 필요 없이 최종 목적지 하나만 보여주면 충분하므로, 연속 구간에서
    마지막 이동 파트만 남기고 나머지는 버린다. 다른 행동이 사이에 끼면
    (이동/5열-공격/대상-이동/6열) 연속이 아니므로 그대로 각각 남는다.

    `format_battle_reply()`가 파트 리스트 전체를 한 번에 받는 경로(본
    전투/DM 전투/대련의 직접 커맨드)뿐 아니라, admin.py의
    `_format_named_reply()`처럼 파트를 하나씩 잘라 개별 블록으로 조립하는
    프록시 경로에서도 그 루프를 돌기 전에 먼저 이 함수로 걸러야 한다."""
    filtered: list[CommandPartProcessResult] = []
    for i, part_result in enumerate(part_results):
        next_result = part_results[i + 1] if i + 1 < len(part_results) else None
        if _is_move_part(part_result) and _is_move_part(next_result):
            continue
        filtered.append(part_result)
    return filtered


def _is_move_part(part_result: Optional[CommandPartProcessResult]) -> bool:
    if part_result is None:
        return False
    original_part = part_result.expanded_part.original_part
    return original_part is not None and original_part.type_ == ActionType.MOVE


def format_eliminated_characters(eliminated: list[CharacterId]) -> str:
    """라운드 종료 시 체력 0으로 필드에서 제거된 캐릭터 목록을
    "【탈락】\n▹ {이름}" 블록으로 조립한다. 없으면 빈 문자열."""
    if not eliminated:
        return ""
    lines = "\n".join(f"▹ {char_id.name}" for char_id in eliminated)
    return f"**【탈락】**\n{lines}"


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
        header = f"**【라운드 종료 처리 ▸ {target_name}】**"
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
    header = "**【전투 종료 처리】**"
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
    header = _format_header(caster_id, part, part_result.redirect_map)
    return part, header, part_result.log_entries


def _format_part(
    context: "BattlefieldContext",
    caster_id: CharacterId,
    part_result: CommandPartProcessResult,
    show_skill_preview: bool,
    merged_lines: dict[tuple[BattleLogEntryKind, str], str],
    emitted: set[tuple[BattleLogEntryKind, str]],
) -> tuple[str, str]:
    part, header, log_entries = _header_and_log_entries(caster_id, part_result)

    body_lines = []
    if show_skill_preview and part.type_ == ActionType.SKILL:
        # 예고 미리보기는 적 PRE 선언 전용이라, 이 시점엔 대미지/힐 등
        # 실제 결과가 아직 없는 경우(대부분)가 많다 — 그때도 무엇을
        # 선언했는지(대상)는 알아야 하므로 헤더를 항상 함께 보여준다.
        body_lines.append(header)
        body_lines.append(_format_skill_preview(context, part))

    calc_lines = []
    for entry in log_entries:
        line, calc, final_value = _format_entry(context, entry)
        if entry.kind in _MERGEABLE_KINDS:
            # 같은 대상의 대미지/회복이 다른 파트(예: 공격을 여러 번 나눠
            # 선언)에 이미 합산 줄로 나갔으면 본문에는 또 넣지 않는다 —
            # 계산식(calc_lines)은 이 파트 고유의 굴림이므로 그대로 남긴다.
            key = (entry.kind, entry.target_name)
            if key not in emitted:
                emitted.add(key)
                body_lines.append(merged_lines.get(key, line))
        else:
            body_lines.append(line)
        if calc:
            calc_lines.append(f"▹ {entry.target_name} | {calc} → {final_value}")

    # 적 후행 정산으로 미뤄지는 공격 등, 이 시점엔 아직 아무 결과도 없는
    # 파트(예: PRE 선언)는 보여줄 결과 줄이 없다 — 그래도 커맨드가
    # 접수됐다는 확인 자체는 필요하므로 이때만 예외적으로 헤더로 대체한다.
    # (대미지/회복이 전부 다른 파트의 합산 줄로 흡수돼 body_lines가 비는
    # 경우는 log_entries 자체는 있었으므로 구분해서, 헤더를 또 보여주지
    # 않고 빈 문자열을 반환한다 — 호출측이 그대로 건너뛴다.)
    if body_lines:
        body = "\n".join(body_lines)
    elif not log_entries:
        body = header
    else:
        body = ""
    calc_block = f"{header}\n" + "\n".join(calc_lines) if calc_lines else ""
    return body, calc_block


_BLIND_SKILL_TEXT = "[효과 미확인]"


def _format_skill_preview(context: "BattlefieldContext", part: CommandPart) -> str:
    assert part.skill_id is not None
    skill_data = context.get_skill_data_by_id(part.skill_id)
    text = skill_data.description if skill_data.revealed else _BLIND_SKILL_TEXT
    return f"　↳ {text}"


def _format_header(
    caster_id: CharacterId,
    part: CommandPart,
    redirect_map: dict[CharacterId, CharacterId],
) -> str:
    if part.type_ == ActionType.MOVE:
        column = part.targets[0]
        return f"**【이동 ▸ {column}열】**"
    if part.type_ == ActionType.ATTACK:
        return f"**【공격 ▸ {_target_label(part.targets, redirect_map)}】**"
    if part.type_ == ActionType.SKILL:
        return (
            f"**【{part.skill_id} ▸ "
            f"{_skill_target_label(caster_id, part.targets, redirect_map)}】**"
        )
    if part.type_ == ActionType.USE_ITEM:
        return (
            f"**【{part.item_id} ▸ "
            f"{_skill_target_label(caster_id, part.targets, redirect_map)}】**"
        )
    raise ValueError(part.type_)


def _skill_target_label(
    caster_id: CharacterId,
    targets: list,
    redirect_map: dict[CharacterId, CharacterId],
) -> str:
    # 자가 대상 스킬(SkillTargetRuleSelf)은 사용자가 대상을 입력하지 않아
    # targets가 비어 있다 — 이 경우 시전자 자신의 이름을 보여준다.
    if not targets:
        return caster_id.name
    return _target_label(targets, redirect_map)


def _target_label(targets: list, redirect_map: dict[CharacterId, CharacterId]) -> str:
    return ", ".join(_target_name(target, redirect_map) for target in targets)


def _target_name(target: object, redirect_map: dict[CharacterId, CharacterId]) -> str:
    if not isinstance(target, CharacterId):
        return f"{target}열"  # BattlefieldColumnIndex
    # 도발/희생 방어로 실제 대상이 치환됐으면(예: 도발) 원래 대상과 실제
    # 대상을 함께 보여준다 — 답글만 봐도 왜 이 대상이 맞았는지 알 수 있게.
    redirected_to = redirect_map.get(target)
    if redirected_to is not None and redirected_to != target:
        return f"{target.name} ▸ {redirected_to.name}"
    return target.name


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
        # entry.result는 build_log_entries()가 그 이동이 적용된 시점의
        # move_data.to_position으로 이미 만들어 둔 값이다 — 여기서
        # context.find_character_position()으로 다시 조회하면, 한 커맨드
        # 안에서 이동이 여러 번 나뉘어 있을 때(예: 이동/2열-이동/3열-이동/4열)
        # 모든 이동이 이미 끝난 뒤(최종 위치 기준)에 포매팅이 일어나므로
        # 각 파트가 실제로 어디로 이동했는지와 무관하게 전부 최종 위치로
        # 보이는 문제가 있었다.
        return f"▹ {entry.target_name} | {entry.result}", None, None
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
    label_suffix = "".join(f" [{label}]" for label in entry.source_labels)
    if entry.hp_after is None:
        # 대미지로 사망해 전장에서 제거된 경우 등 — 잔여 체력을 보여줄 수 없다.
        line = f"▹ {entry.target_name} | {final_value}{label_suffix}"
    else:
        line = (
            f"▹ {entry.target_name} | {final_value} → "
            f"{entry.hp_after}/{entry.max_hp}{label_suffix}"
        )
    return line, entry.roll_display, final_value
