from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffAddData, BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import ActionType, BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class ApplyDebuffOnDealingDamageEvent(BuffEvent):
    """holder가 이번 effect에서 실제로 대미지를 준 대상 각각에게
    reference_buff_id 버프를 부여한다.

    ON_ACTION은 공격자/피격자 양쪽에서 호출되므로, 직접 damage_data_list를
    훑어 attacker_id == holder인 항목만 골라야 방향(내가 때릴 때만)을
    보장할 수 있다(BonusDamageOnHitEvent와 동일한 패턴). "기본 공격이나
    스킬로"라는 설명대로 ActionType.USE_ITEM(대미지를 주는 아이템 사용)은
    제외한다.
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

        if calculator.action_type == ActionType.USE_ITEM:
            return

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
            # 일반 경로(buff_add_data_list)는 페이즈가 맞아야만 로그를 남기므로,
            # 직접 add()한 이 부여는 로그가 빠질 수 있다 — 직접 얹는다.
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
