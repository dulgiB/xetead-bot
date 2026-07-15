from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming
from battle.objects.models import CharacterId

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.core.command_calculator import CommandPartCalculator


@dataclass(frozen=True)
class CatastropheNoopEvent(BuffEvent):
    """[재앙]은 자연적으로 발동하는 효과가 없는 순수 카운터 버프다. 스킬 효과
    (SkillEffectConsumeStackForDamage 등)가 스택을 직접 조회·소모하므로 여기서는
    아무 일도 하지 않는다."""

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
        pass


class BuffCatastrophe(BuffBase):
    """[재앙]: 버프도 디버프도 아닌 순수 적층형 마커. 해제할 수 없고(패시브
    지속시간이라 라운드 종료 시 자동 제거되지 않으며, is_debuff=False라
    디버프 해제 효과의 대상이 되지 않는다), 전투가 끝나면 남은 스택 × 3만큼
    시전자의 체력을 깎는다."""

    @property
    def timing(self) -> BuffApplyTiming:
        return BuffApplyTiming.ON_ROUND_END

    def create_event(self) -> BuffEvent:
        return CatastropheNoopEvent(condition=self.condition)

    def on_battle_end(self, context: "BattlefieldContext") -> None:
        if self.stack_count <= 0:
            return
        character = context.characters.get(self.applied_to)
        if character is None:
            return
        character.status.curr_hp = max(0, character.status.curr_hp - self.stack_count * 3)
