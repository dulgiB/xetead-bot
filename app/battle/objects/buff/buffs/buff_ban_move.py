from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buffs.buff_ban_action import BanActionEvent
from battle.objects.define import ActionType, BuffApplyTiming


class BuffBanMove(BuffBase):
    @property
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_MOVE}

    def create_event(self) -> BanActionEvent:
        return BanActionEvent(
            condition=self.condition,
            banned_actions=[ActionType.MOVE],
        )
