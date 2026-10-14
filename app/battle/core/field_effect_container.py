from dataclasses import replace
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

    상시 효과는 remove()하기 전까지 유지되고, 일시 효과는 tick_turns()가
    라운드 종료마다 남은 턴을 줄이다가 0이 되면 같은 remove() 경로로 걷는다.
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

    def as_display_list(self) -> list[FieldEffect]:
        effects = self.as_list()
        return [e for e in effects if not e.is_temporary] + [
            e for e in effects if e.is_temporary
        ]

    def add(
        self,
        data: PassiveSkillData,
        source: FieldEffectSource,
        source_detail: str = "",
        turns: Optional[int] = None,
    ) -> Optional[FieldEffect]:
        """필드 효과를 전장에 올린다. `turns`가 None이면 상시 효과다.

        이미 같은 id가 걸려 있으면 다시 올리지 않고 지속시간만 다룬다. 상시
        효과는 그대로 두고 None을 반환한다. 일시 효과는 남은 턴을 새 값으로
        바꾸고(`turns`가 None이면 상시로 바뀐다) 갱신된 효과를 반환한다 —
        버프 재부여가 지속시간을 갱신하는 것과 같은 규칙이다.
        """
        existing = self._effects.get(data.id)
        if existing is not None:
            if not existing.is_temporary:
                return None
            refreshed = replace(
                existing,
                source=source,
                source_detail=source_detail,
                remaining_turns=turns,
            )
            self._effects[data.id] = refreshed
            return refreshed

        effect = FieldEffect(
            data=data,
            source=source,
            source_detail=source_detail,
            remaining_turns=turns,
        )
        self._effects[data.id] = effect

        for wrapper in PassiveSkillWrapperBuff.create(effect.holder_id, data):
            self._context.buff_container.add_passive_wrapper(wrapper)

        for char_id in self._targets_of(effect):
            self._apply_standing_states(effect, char_id, revert=False)

        return effect

    def remove(self, effect_id: str) -> Optional[FieldEffect]:
        """필드 효과를 걷는다. 래퍼뿐 아니라 **그 효과가 부여한 버프까지**
        회수한다 — 홀더 센티넬이 효과마다 고유하므로 given_by로 자기 것만
        정확히 골라낼 수 있다."""
        effect = self._effects.pop(effect_id, None)
        if effect is None:
            return None

        for char_id in self._targets_of(effect):
            self._apply_standing_states(effect, char_id, revert=True)

        self._context.buff_container.remove_buffs_given_by(effect.holder_id)
        return effect

    def tick_turns(self) -> list[FieldEffect]:
        """라운드 종료 처리. 일시 효과의 남은 턴을 1씩 줄이고, 0이 된 효과를
        걷어 반환한다."""
        expired: list[FieldEffect] = []
        for effect in self.as_list():
            if effect.remaining_turns is None:
                continue
            remaining = effect.remaining_turns - 1
            if remaining > 0:
                self._effects[effect.id] = replace(effect, remaining_turns=remaining)
                continue
            if (removed := self.remove(effect.id)) is not None:
                expired.append(removed)
        return expired

    def clear(self) -> None:
        for effect_id in list(self._effects):
            self.remove(effect_id)

    def apply_to_newcomer(self, char_id: CharacterId) -> None:
        """전투 도중 참전한 캐릭터에게 이미 걸려 있는 필드 효과를 즉시
        반영한다. 이게 없으면 "전투 시작" 트리거 효과는 영영 못 받고
        "라운드 시작" 트리거 효과는 한 라운드 늦게 받는다."""
        for effect in self._effects.values():
            # 진영 범위 판정은 정규 경로와 똑같은 함수를 거쳐야 한다 —
            # 참전 경로가 따로 진영을 따지면 두 경로의 규칙이 갈린다.
            if char_id not in self._targets_of(effect):
                continue

            # 상시 상태 효과는 트리거와 무관하게 걸려 있는 동안 유지되는 상태다.
            self._apply_standing_states(effect, char_id, revert=False)

            if effect.data.trigger not in _STANDING_TRIGGERS:
                continue
            self._apply_effects_to(effect, [char_id])

    def _targets_of(self, effect: FieldEffect) -> list[CharacterId]:
        return resolve_passive_targets(
            self._context, effect.holder_id, None, effect.data.target_type
        )

    def _apply_standing_states(
        self, effect: FieldEffect, char_id: CharacterId, *, revert: bool
    ) -> None:
        """이 필드 효과의 상시 상태 효과를 한 캐릭터에게 얹거나 되돌린다."""
        character = self._context.characters.get(char_id)
        if character is None:
            return

        for skill_effect in effect.data.effects:
            skill_effect.apply_standing_state(character.status, revert=revert)

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
