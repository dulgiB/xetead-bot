"""에너미 특성 패시브용 모디파이어. 모두 "버프_패시브" 시트의
buff_mod_event 경로(PassiveSkillData.buff_mod_event)로 쓰고, "버프" 시트에
직접 등록해 부여하는 용도가 아니다."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class StripBuffsOnHitEvent(BuffEvent):
    """holder가 이번 effect에서 공격한 대상 각각의 버프를 그 대미지 뒤에
    전부 해제하도록 계산기에 요청한다(실제 해제는
    CommandPartCalculator._process_buff_strip()).

    ON_ACTION은 공격자/피격자 양쪽에서 호출되므로 attacker_id == holder인
    항목만 고른다."""

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(
        self,
        holder: CharacterId,
        attacker_or_target: CharacterId,
        calculator: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        effect_data = calculator.data_by_effect[effect_seq_number]
        requests = calculator._buff_strip_requests.setdefault(effect_seq_number, set())
        for damage_data in effect_data.damage_data_list:
            base = damage_data.base
            if base.attacker_id != holder or base.target_id == holder:
                continue
            requests.add((holder, base.target_id))


class BuffStripBuffsOnHit(BuffBase):
    """보유자에게 공격당한 대상은 그 시점에 걸려 있던 버프(패시브 제외)가
    모두 해제된다. 디버프와 "기타"(해제 불가 마커·부적 등)는 건드리지 않는다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> StripBuffsOnHitEvent:
        return StripBuffsOnHitEvent(condition=self.condition)
