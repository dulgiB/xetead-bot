from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BanActionEvent
from battle.objects.define import ActionType, BuffApplyTiming


class BuffBanMove(BuffBase):
    def timing(self) -> set[BuffApplyTiming]:
        return {BuffApplyTiming.ON_MOVE}

    def apply(self) -> BanActionEvent:
        return BanActionEvent(
            condition=self.condition,
            banned_actions=[ActionType.MOVE],
        )
