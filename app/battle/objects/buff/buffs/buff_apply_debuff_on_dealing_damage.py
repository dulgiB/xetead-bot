from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class ApplyDebuffOnDealingDamageEvent(BuffEvent):
    """holder가 이번 effect에서 실제로 대미지를 준 대상 각각에게
    reference_buff_id 버프를 부여한다.

    ON_ACTION은 공격자/피격자 양쪽에서 호출되므로, 직접 damage_data_list를
    훑어 attacker_id == holder인 항목만 골라야 방향(내가 때릴 때만)을
    보장할 수 있다(BonusDamageOnHitEvent와 동일한 패턴).
    """

    reference_buff_id: str

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
        from battle.core.command_calculator import build_buff_add_log_entry

        effect_data = calculator.data_by_effect[effect_seq_number]
        for damage_data in effect_data.damage_data_list:
            base = damage_data.base
            if base.attacker_id != holder or not base.triggers_given_damage_passives:
                continue
            if base.target_id not in calculator.context.characters:
                continue
            buff_add = BuffAddData(
                given_by=holder,
                applied_to=base.target_id,
                buff_id=self.reference_buff_id,
            )
            calculator.context.buff_container.add(buff_add)
            # _process_buff_add()의 일반 경로(buff_add_data_list)는 PRE/POST
            # 페이즈에 따라 add_timing이 일치해야만 처리되므로, 여기서 직접
            # buff_container.add()를 호출한 부여는 그 경로로 로그가 남는다는
            # 보장이 없다 — extra_log_entries에 직접 얹어 이 대미지와 같은
            # 답글 블록에 확실히 포함시킨다.
            effect_data.extra_log_entries.append(
                build_buff_add_log_entry(calculator.context, buff_add)
            )


class BuffApplyDebuffOnDealingDamage(BuffBase):
    """기본 공격이나 스킬로 대미지를 줄 때마다, 대상에게 reference_buff_id
    버프를 부여하는 패시브 모디파이어. "버프_패시브" 시트의 buff_mod_event
    경로(PassiveSkillData.buff_mod_event) 전용이다.
    """

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ACTION

    def create_event(self) -> ApplyDebuffOnDealingDamageEvent:
        assert self.reference_buff_id is not None
        return ApplyDebuffOnDealingDamageEvent(
            condition=self.condition,
            reference_buff_id=self.reference_buff_id,
        )
