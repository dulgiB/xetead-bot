from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buffs.buff_damage_over_time import DamageOverTimeEvent
from battle.objects.define import BuffApplyTiming


class BuffConditionalDamage(BuffBase):
    """ENEMY_POST_ACTION 타이밍에 조건이 만족되면 대미지를 입힌다.
    Condition 조합 필수!

    value: 고정 대미지 수치.
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ENEMY_POST_ACTION

    def create_event(self) -> DamageOverTimeEvent:
        return DamageOverTimeEvent(condition=self.condition, value=self.value)
