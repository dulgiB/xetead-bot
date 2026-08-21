import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.command_calculator import CommandPartCalculator


@dataclass
class _RedirectableInstance:
    calculator: "CommandPartCalculator"
    original_target: CharacterId


def get_active_taunters(
    context: "BattlefieldContext", attacker_id: CharacterId
) -> list[CharacterId]:
    """attacker_id에게 걸린 모든 도발자를 이름순으로 반환한다. BuffContainer의
    내부 저장소는 set이라 자연 순서가 없으므로, 재현 가능한 처리 순서를 위해
    명시적으로 정렬한다."""
    taunters = {
        override
        for buff in context.buff_container.get_buffs_by(
            attacker_id, BuffApplyTiming.ON_ACTION
        )
        if (override := buff.get_target_override()) is not None
    }
    return sorted(taunters, key=lambda cid: cid.name)


def _collect_redirectable_instances(
    calculators: list["CommandPartCalculator"],
    phase: Optional[RoundPhaseType],
) -> list[_RedirectableInstance]:
    """이 배치에서 실제로 대미지가 적용될 '독립 공격 인스턴스' 목록을 선언
    순서대로 만든다. 계산기 하나(=CommandPart 하나) 안에서 같은 대상을 여러
    effect가 때리는 것은 한 인스턴스로 묶는다(대상 캐릭터 기준). 서로 다른
    계산기(=서로 다른 CommandPart, 같은 대상을 여러 번 선언한 경우 포함)는
    항상 독립 인스턴스로 취급한다. ignores_taunt(열 광역기 등) 항목은 제외한다.
    """
    instances: list[_RedirectableInstance] = []
    for calculator in calculators:
        seen: set[CharacterId] = set()
        for mutable in calculator.data_by_effect:
            if not calculator._damage_processed_in_phase(mutable.apply_timing, phase):
                continue
            for damage_calc in mutable.damage_data_list:
                if damage_calc.base.ignores_taunt:
                    continue
                target = damage_calc.base.target_id
                if target in seen:
                    continue
                seen.add(target)
                instances.append(_RedirectableInstance(calculator, target))
    return instances


def assign_taunt_redirects(
    context: "BattlefieldContext",
    attacker_id: CharacterId,
    calculators: list["CommandPartCalculator"],
    phase: Optional[RoundPhaseType],
) -> None:
    """이 배치(한 캐릭터가 이번에 선언한 공격 인스턴스 전체)에 대해 도발
    리다이렉트를 미리 결정해 각 calculator의 precomputed_taunt_redirects에
    채워 넣는다. 각 calculator.process()를 호출하기 전에 반드시 실행해야 한다.

    이미 어떤 도발자를 직접 겨냥한 인스턴스는 고정되어 재추첨 풀에서 제외된다
    (다른 도발자가 가로채지 못한다). 남은 풀에서 도발자 각각(이름순)이 무작위로
    인스턴스를 하나씩 뽑아 자신에게 리다이렉트한다. 풀이 먼저 바닥나면 남은
    도발자는 이번엔 리다이렉트를 받지 못한다.
    """
    for calculator in calculators:
        calculator.precomputed_taunt_redirects = {}

    taunters = get_active_taunters(context, attacker_id)
    if not taunters:
        return

    taunter_set = set(taunters)
    pool = [
        inst
        for inst in _collect_redirectable_instances(calculators, phase)
        if inst.original_target not in taunter_set
    ]

    for taunter in taunters:
        if not pool:
            break
        chosen = random.choice(pool)
        pool.remove(chosen)
        redirects = chosen.calculator.precomputed_taunt_redirects
        assert redirects is not None  # 이 함수 시작부에서 모든 calculator에 채워둠
        redirects[chosen.original_target] = taunter
