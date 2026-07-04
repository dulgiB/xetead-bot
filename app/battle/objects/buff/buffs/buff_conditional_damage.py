from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buffs.buff_damage_over_time import DamageOverTimeEvent
from battle.objects.define import BuffApplyTiming, ValueType


class BuffConditionalDamage(BuffBase):
    """ENEMY_POST_ACTION 타이밍에 조건이 만족되면 대미지를 입힌다.
    Condition 조합 필수!

    value: 고정 대미지 수치. value_type은 반드시 정수여야 한다.
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ENEMY_POST_ACTION

    def create_event(self) -> DamageOverTimeEvent:
        if self.value_type is not None and self.value_type != ValueType.INTEGER:
            raise ValueError(self.value_type)
        return DamageOverTimeEvent(condition=self.condition, value=self.value)
