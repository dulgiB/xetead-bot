from typing import TYPE_CHECKING

from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.command_calculator import CommandPartCalculator
    from battle.core.commands.models import DamageCalculateData


def apply_pure_damage_modifiers_to(
    new_damage_calc: "DamageCalculateData",
    attacker_id: CharacterId,
    target_id: CharacterId,
    calculator: "CommandPartCalculator",
    effect_seq_number: int,
) -> None:
    """제3자 반응형(피동적) 대미지 항목 하나에, attacker_id/
    target_id가 평소 자신의 행동에서 받는 "주는/받는 대미지" 수정자를 반영한다.

    GivenDamageModEvent 등 일반 ON_ACTION 이벤트는 호출될 때마다 이 effect의
    damage_data_list 전체를 훑어 attacker_id/target_id가 일치하는 모든 항목에
    무조건 수정자를 추가한다. 이미 처리된 기존 항목이 섞인 채로 다시 호출하면
    그 항목들에 중복 적용되므로, new_damage_calc 하나만 담은 목록으로 리스트를
    잠깐 바꿔치기해 이벤트가 이 항목만 보게 한 뒤 원래 리스트로 되돌리고
    new_damage_calc를 이어붙인다.

    is_pure_damage_modifier=True인 이벤트만 골라 재실행한다 — 리다이렉트·
    무효화·새 대미지 항목 추가 같은 부수효과가 있는 이벤트(도발/반사/희생
    방어 등)까지 격리된 임시 목록에 대고 실행하면 원본 리스트를 벗어난
    범위에서 잘못된 부수효과를 낼 수 있기 때문이다."""
    effect_data = calculator.data_by_effect[effect_seq_number]
    original_list = effect_data.damage_data_list
    effect_data.damage_data_list = [new_damage_calc]
    try:
        for owner, other in ((attacker_id, target_id), (target_id, attacker_id)):
            for buff in calculator.context.buff_container.get_buffs_by(
                owner, BuffApplyTiming.ON_ACTION
            ):
                event = buff.create_event()
                if not event.is_pure_damage_modifier:
                    continue
                if event.is_applied(calculator.context, owner, other):
                    event.apply(owner, other, calculator, effect_seq_number)
    finally:
        effect_data.damage_data_list = original_list
    original_list.append(new_damage_calc)
