"""합동 스킬: 짝이 된 아군이 같은 라운드에 함께 선언해야 발동하는 스킬.

먼저 선언한 쪽은 코스트만 내고 대기 상태로 남는다(PendingJointSkill). 짝이
같은 라운드에 선언하면 효과가 한 번 발동하며, 시전자는 먼저 선언한 쪽이다 —
버프 부여자·위치·공격력 계수가 그 사람 기준이다. 라운드가 끝날 때까지 짝이
선언하지 않으면 대기는 풀리고 낸 코스트는 돌려주지 않는다.
"""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Optional

from battle.core.commands.models import (
    BattleLogEntry,
    BattleLogEntryKind,
    CommandPart,
)
from battle.exceptions import (
    CommandValidationError,
    error_joint_already_declared,
    error_joint_keyword_not_allowed,
    error_joint_partner_not_on_field,
    error_joint_skill_already_used,
    error_joint_skill_locked,
    error_joint_target_mismatch,
    error_joint_target_out_of_range,
    error_target_does_not_exist,
)
from battle.objects.define import BattlefieldColumnIndex, CombatStatType
from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillData
from utils.battle_helpers import is_reachable_between

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext

JointTarget = CharacterId | BattlefieldColumnIndex


@dataclass(frozen=True)
class PendingJointSkill:
    skill_id: str
    declarer: CharacterId
    targets: tuple[JointTarget, ...]


def joint_partner_of(
    context: "BattlefieldContext", skill_id: str, user_id: CharacterId
) -> Optional[PendingJointSkill]:
    """user가 이 합동 스킬을 선언하면 짝의 대기에 합류하는지. 합류한다면 그
    대기를, 이번 선언이 먼저 하는 선언이면 None을 돌려준다."""
    pending = context.joint_pending.get(skill_id)
    if pending is None or pending.declarer == user_id:
        return None
    return pending


def validate_joint_part(
    context: "BattlefieldContext",
    user_id: CharacterId,
    part: CommandPart,
    skill: SkillData,
) -> CommandPart:
    """합동 스킬 선언을 검증하고, 짝의 대기에 합류하는 선언이면 대상을 짝이
    지정한 대상으로 채운 파트를 돌려준다."""
    if part.keyword_boost:
        raise CommandValidationError(error_joint_keyword_not_allowed())
    if not skill.joint_unlocked:
        raise CommandValidationError(error_joint_skill_locked(skill.id))
    if skill.id in context.joint_used:
        raise CommandValidationError(error_joint_skill_already_used(skill.id))

    pending = context.joint_pending.get(skill.id)
    if pending is not None and pending.declarer == user_id:
        raise CommandValidationError(error_joint_already_declared(skill.id))

    members, missing = context.joint_skill_members(skill)
    if missing:
        raise CommandValidationError(
            error_joint_partner_not_on_field(skill.id, missing)
        )

    if pending is not None:
        if part.targets and tuple(part.targets) != pending.targets:
            raise CommandValidationError(error_joint_target_mismatch(skill.id))
        part = replace(part, targets=list(pending.targets))

    for target in part.targets:
        if isinstance(target, CharacterId):
            if target not in context.characters:
                raise CommandValidationError(error_target_does_not_exist(target))
            target_columns = context.find_character_columns(target)
        else:
            target_columns = (target,)
        for member in members:
            if not is_reachable_between(
                context.find_character_columns(member),
                target_columns,
                context.characters[member].status[CombatStatType.RANGE],
            ):
                raise CommandValidationError(
                    error_joint_target_out_of_range(skill.id, member)
                )
    return part


def joint_waiting_entry(skill_id: str, user_id: CharacterId) -> BattleLogEntry:
    return BattleLogEntry(
        target_name=user_id.name,
        kind=BattleLogEntryKind.JOINT_SKILL,
        result=f"합동 스킬 「{skill_id}」 선언 — 짝의 선언을 기다립니다",
    )


def joint_fired_entry(
    skill_id: str, user_id: CharacterId, pending: PendingJointSkill
) -> BattleLogEntry:
    return BattleLogEntry(
        target_name=user_id.name,
        kind=BattleLogEntryKind.JOINT_SKILL,
        result=f"합동 스킬 「{skill_id}」 발동 — 시전자 {pending.declarer.name}",
    )


def joint_expired_entry(pending: PendingJointSkill) -> BattleLogEntry:
    return BattleLogEntry(
        target_name=pending.declarer.name,
        kind=BattleLogEntryKind.JOINT_SKILL,
        result=f"합동 스킬 「{pending.skill_id}」 불발 — 짝이 선언하지 않았습니다",
    )


def dump_joint_state(context: "BattlefieldContext") -> dict:
    """재기동 복원용 합동 스킬 상태. 어느 시트에도 진실 공급원이 없다."""
    return {
        "used": sorted(context.joint_used),
        "pending": [
            {
                "skill_id": pending.skill_id,
                "declarer": pending.declarer.name,
                "targets": [
                    {"name": target.name}
                    if isinstance(target, CharacterId)
                    else {"column": target.value}
                    for target in pending.targets
                ],
            }
            for pending in context.joint_pending.values()
        ],
    }


def load_joint_state(context: "BattlefieldContext", data: dict) -> None:
    context.joint_used = set(data.get("used", []) or [])
    context.joint_pending = {}
    for entry in data.get("pending", []) or []:
        targets: list[JointTarget] = [
            CharacterId(target["name"])
            if "name" in target
            else BattlefieldColumnIndex(int(target["column"]))
            for target in entry.get("targets", [])
        ]
        pending = PendingJointSkill(
            str(entry["skill_id"]), CharacterId(str(entry["declarer"])), tuple(targets)
        )
        context.joint_pending[pending.skill_id] = pending
