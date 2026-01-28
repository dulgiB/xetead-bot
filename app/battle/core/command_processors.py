from typing import TYPE_CHECKING

from battle.admin_utils import (
    AdminCommandData,
    ChangePhaseCommand,
    ChangePhaseCommandData,
)
from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.models import (
    BanResult,
    CharacterCommandData,
    CommandProcessResult,
)
from battle.exceptions import CommandValidationError
from battle.objects.buff.buffs.buff_ban_action import BanActionEvent
from battle.objects.define import BuffApplyTiming
from battle.objects.models import ValueWithModifiers

if TYPE_CHECKING:
    from battle.core.round_manager import RoundManager


def process_admin_command(
    round_manager: "RoundManager", command: AdminCommandData
) -> None:
    if isinstance(command, ChangePhaseCommandData):
        round_manager.to_phase(command.target_phase)


def is_valid(context: BattlefieldContext, command: CharacterCommandData) -> bool:
    return True


def process_ally_command(
    context: BattlefieldContext, command: CharacterCommandData
) -> CommandProcessResult:
    if not is_valid(context, command):
        raise CommandValidationError()

    # 스턴 등 캐릭터가 행동할 수 없는 상태인지 체크
    character_action_buffs = context.buff_container.get_buffs_by(
        command.command.user, BuffApplyTiming.ON_ACTION
    )
    character_action_events = [buff.apply() for buff in character_action_buffs]
    ban_action_events = [
        event for event in character_action_events if isinstance(event, BanActionEvent)
    ]
    ban_event_results = [
        BanResult(event.is_applied(), event) for event in ban_action_events
    ]
    for ban_result in ban_event_results:
        if ban_result.is_banned:
            return CommandProcessResult(command_data=command, ban_result=ban_result)

    for move_data in command.move_list:
        context.move_character_to(move_data.character_id, move_data.to_position)

    for damage_data in command.damage_list:
        attacker_buff_list = context.buff_container.get_buffs_by(
            damage_data.attacker_id, BuffApplyTiming.ON_ATTACK
        )
        attacker_events = [buff.apply() for buff in attacker_buff_list]

        attack_target_buff_list = context.buff_container.get_buffs_by(
            damage_data.target_id, BuffApplyTiming.ON_HIT
        )
        target_events = [buff.apply() for buff in attack_target_buff_list]

        context.apply_damage(
            damage_data.attacker_id,
            damage_data.target_id,
            ValueWithModifiers(damage_data.value, attacker_events + target_events),
        )

    for heal_data in command.heal_list:
        healer_buff_list = context.buff_container.get_buffs_by(
            heal_data.healer_id, BuffApplyTiming.ON_GIVE_HEAL
        )
        healer_modifiers = [buff.apply() for buff in healer_buff_list]

        heal_target_buff_list = context.buff_container.get_buffs_by(
            heal_data.target_id, BuffApplyTiming.ON_RECEIVE_HEAL
        )
        heal_target_modifiers = [buff.apply() for buff in heal_target_buff_list]

        context.apply_heal(
            heal_data.healer_id,
            heal_data.target_id,
            ValueWithModifiers(
                heal_data.value, healer_modifiers + heal_target_modifiers
            ),
        )

    for buff_add_event in command.buff_add_list:
        context.buff_container.add(buff_add_event)

    for buff_remove_event in command.buff_remove_list:
        context.buff_container.remove(buff_remove_event)

    return CommandProcessResult(command_data=command)


def process_enemy_command(
    context: BattlefieldContext, command: CharacterCommandData
) -> None:
    pass
