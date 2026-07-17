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
from battle.objects.define import ActionType
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


def format_battle_reply(
    context: "BattlefieldContext",
    caster_id: CharacterId,
    part_results: list[CommandPartProcessResult],
) -> str:
    blocks = [
        _format_part(context, caster_id, part_result) for part_result in part_results
    ]
    return "\n\n".join(blocks)


def _format_part(
    context: "BattlefieldContext",
    caster_id: CharacterId,
    part_result: CommandPartProcessResult,
) -> str:
    part = part_result.expanded_part.original_part
    assert isinstance(part, CommandPart)
    header = _format_header(caster_id, part)

    # 최상위 [이동] 커맨드는 헤더 한 줄이 전부다 (스킬 효과로서의 이동과 다름).
    if part.type_ == ActionType.MOVE:
        return header

    body_lines = [_format_entry(context, entry) for entry in part_result.log_entries]
    if not body_lines:
        return header
    return header + "\n" + "\n".join(body_lines)


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
    if entry.kind == BattleLogEntryKind.DAMAGE:
        return _format_damage_or_heal(entry, sign="-")
    if entry.kind == BattleLogEntryKind.HEAL:
        return _format_damage_or_heal(entry, sign="+")
    if entry.kind == BattleLogEntryKind.MOVE:
        target_id = CharacterId(entry.target_name)
        position = context.find_character_position(target_id)
        return f"{entry.target_name} | {position}열로 이동"
    # BUFF_ADD/BUFF_REMOVE/DEBUFF_CLEAR는 이미 build_log_entries()가 만들어 둔
    # result 문자열을 그대로 쓴다.
    return f"{entry.target_name} | {entry.result}"


def _format_damage_or_heal(entry: BattleLogEntry, *, sign: str) -> str:
    # entry.hp_after/max_hp는 이 대미지/회복이 적용된 "그 시점"의 스냅샷이다.
    # 같은 커맨드에서 같은 대상이 여러 번 맞을/회복될 수 있어(효과 2개 이상),
    # context를 여기서 다시 조회하면 전부 최종 HP로 보이게 되므로 쓰면 안 된다.
    if entry.hp_after is None:
        # 대미지로 사망해 전장에서 제거된 경우 등 — 잔여 체력을 보여줄 수 없다.
        line = f"{entry.target_name} | {sign}{entry.value}"
    else:
        line = f"{entry.target_name} | {sign}{entry.value} → {entry.hp_after}/{entry.max_hp}"
    if entry.roll_display:
        line += f"\n↳ {entry.roll_display}"
    return line
