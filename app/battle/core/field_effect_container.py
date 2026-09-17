import logging
from typing import TYPE_CHECKING, Iterator, Optional

from battle.objects.buff.buff_base import BuffBase
from battle.objects.field_effect.models import FieldEffect, FieldEffectSource
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTrigger,
)
from battle.objects.passive_skill.passive_skill import (
    PassiveSkillWrapperBuff,
    resolve_passive_targets,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext

logger = logging.getLogger(__name__)

# 중간 참전자에게 곧바로 다시 적용해 주는 트리거. "지속 상태"를 세우는
# 트리거만 해당한다 — 반응형 트리거(적 이동 시 등)는 그 사건이 일어날 때
# 발동하는 것이지, 참전했다고 발동할 일이 아니다.
_STANDING_TRIGGERS = frozenset(
    {PassiveSkillTrigger.BATTLE_START, PassiveSkillTrigger.ROUND_START}
)


class FieldEffectContainer:
    """전장에 걸린 필드 효과들의 생명주기를 관리한다.

    수치 반영 자체는 BuffContainer에 위임한다 — 필드 효과는 자기 센티넬
    홀더로 래퍼 버프를 등록해 두고, 트리거가 오면 기존 패시브 파이프라인이
    그대로 대상들에게 실제 버프를 부여한다. 이 컨테이너가 따로 소유하는 것은
    "무엇이 걸려 있는가"와 "제거할 때 무엇을 되돌리는가"다.

    지속 턴수는 없다. 명시적으로 remove()하기 전까지 유지된다.
    """

    def __init__(self, context: "BattlefieldContext") -> None:
        self._context = context
        self._effects: dict[str, FieldEffect] = {}

    def __iter__(self) -> Iterator[FieldEffect]:
        return iter(self._effects.values())

    def __len__(self) -> int:
        return len(self._effects)

    def __contains__(self, effect_id: str) -> bool:
        return effect_id in self._effects

    def get(self, effect_id: str) -> Optional[FieldEffect]:
        return self._effects.get(effect_id)

    def as_list(self) -> list[FieldEffect]:
        """걸려 있는 필드 효과를 부여된 순서대로 반환한다. 메서드 이름이
        `list`가 아닌 것은 클래스 본문의 `list[...]` 타입 주석을 가리기
        때문이다."""
        return list(self._effects.values())

    def add(
        self,
        data: PassiveSkillData,
        source: FieldEffectSource,
        source_detail: str = "",
    ) -> Optional[FieldEffect]:
        """필드 효과를 전장에 올린다. 이미 같은 id가 걸려 있으면 아무것도
        하지 않고 None을 반환한다 — 지속 턴수가 없어 갱신할 것이 없으므로
        재부여는 무시가 곧 갱신이다."""
        if data.id in self._effects:
            return None

        effect = FieldEffect(data=data, source=source, source_detail=source_detail)
        self._effects[data.id] = effect

        for wrapper in PassiveSkillWrapperBuff.create(effect.holder_id, data):
            self._context.buff_container.add_passive_wrapper(wrapper)

        return effect

    def remove(self, effect_id: str) -> Optional[FieldEffect]:
        """필드 효과를 걷는다. 래퍼뿐 아니라 **그 효과가 부여한 버프까지**
        회수한다 — 홀더 센티넬이 효과마다 고유하므로 given_by로 자기 것만
        정확히 골라낼 수 있다."""
        effect = self._effects.pop(effect_id, None)
        if effect is None:
            return None

        self._context.buff_container.remove_buffs_given_by(effect.holder_id)
        return effect

    def clear(self) -> None:
        for effect_id in list(self._effects):
            self.remove(effect_id)

    def apply_to_newcomer(self, char_id: CharacterId) -> None:
        """전투 도중 참전한 캐릭터에게 이미 걸려 있는 필드 효과를 즉시
        반영한다. 이게 없으면 "전투 시작" 트리거 효과는 영영 못 받고
        "라운드 시작" 트리거 효과는 한 라운드 늦게 받는다."""
        for effect in self._effects.values():
            if effect.data.trigger not in _STANDING_TRIGGERS:
                continue
            # 진영 범위 판정은 정규 경로와 똑같은 함수를 거쳐야 한다 —
            # 참전 경로가 따로 진영을 따지면 두 경로의 규칙이 갈린다.
            in_scope = resolve_passive_targets(
                self._context, effect.holder_id, None, effect.data.target_type
            )
            if char_id not in in_scope:
                continue
            self._apply_effects_to(effect, [char_id])

    def _apply_effects_to(
        self, effect: FieldEffect, targets: list[CharacterId]
    ) -> None:
        """필드 효과의 effect들을 지정한 대상에게만 전개해 버프를 부여한다.

        대미지/회복은 버리고 버프 부여/제거만 반영한다 — 이 경로는 참전처럼
        커맨드 밖에서 불리므로 대미지를 실을 계산기도, 그 결과를 실을 답글도
        없다. 필드 효과의 대미지는 트리거가 왔을 때 정상 경로로 처리된다.
        """
        holder = effect.holder_id
        for skill_effect in effect.data.effects:
            if skill_effect.gate_value_source is not None:
                # 커맨드 처리 중간값에 의존하는 게이트는 이 경로에서 평가할
                # 수 없다(계산기가 없다).
                continue
            condition = skill_effect.condition
            if condition is not None and not condition.is_applied(
                self._context, holder, None
            ):
                continue

            _, _, _, buff_add_list, buff_remove_list = skill_effect.expand(
                self._context, holder, list(targets)
            )
            for buff_add in buff_add_list:
                self._context.buff_container.add(buff_add)
            for buff_remove in buff_remove_list:
                existing: Optional[BuffBase] = self._context.buff_container.get_buff(
                    buff_remove.applied_to, buff_remove.buff_id, given_by=holder
                )
                if existing is not None:
                    self._context.buff_container.remove(existing.uid)
