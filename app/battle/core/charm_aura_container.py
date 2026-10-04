import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.define import ItemType
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from utils.battle_helpers import is_reachable

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CharmAura:
    """전장에 있는 소지자 한 명이 지닌 부적 하나."""

    holder: CharacterId
    item: ItemData
    passive: PassiveSkillData

    @property
    def key(self) -> tuple[CharacterId, str]:
        return (self.holder, self.item.id)


class CharmAuraContainer:
    """부적의 효과를 소지자 사거리 안의 같은 진영 캐릭터(소지자 포함)에게 건다.

    사거리는 소지자의 공격 사거리가 아니라 "아이템" 시트의 `range`다.
    범위는 위치에 따라 바뀌므로 대상 집합은 위치가 바뀔 때마다 refresh()로
    다시 계산하고, 새로 든 대상에게는 얹고 벗어난 대상에게서는 걷는다.

    효과는 상시 상태(SkillEffectBase.is_standing_state)만 쓴다. 트리거형
    효과는 "범위에 있는 동안"이라는 부적의 성격과 맞지 않아 걸지 않는다 —
    걸려 있던 버프를 범위를 벗어날 때 회수하고 재기동 때 되살리는 경로가
    따로 필요해지기 때문이다. 상시 상태는 영속화하지 않아도 배치만으로
    다시 계산된다.
    """

    def __init__(self, context: "BattlefieldContext") -> None:
        self._context = context
        self._auras: dict[tuple[CharacterId, str], CharmAura] = {}
        self._applied: dict[tuple[CharacterId, str], set[CharacterId]] = {}

    def register_holder(self, holder: CharacterId) -> None:
        """holder가 지닌 부적을 모두 등록한다."""
        for item_id in self._context.inventory.items_for_character(holder.name):
            if not self._context.has_item(item_id):
                continue
            item = self._context.get_item_data_by_id(item_id)
            if item.item_type is not ItemType.CHARM:
                continue
            if not item.passive_skill_id:
                continue
            passive = self._context.get_passive_skill_data_by_id(item.passive_skill_id)
            if passive is None:
                # 시트 설정 오류로 전투가 서지 않게 하지 않는다 — [전투개시]
                # 검증이 admin에게 따로 알린다.
                logger.warning(
                    "부적 '%s'의 패시브 '%s'가 '스킬_패시브' 시트에 없어 건너뜁니다",
                    item.id,
                    item.passive_skill_id,
                )
                continue
            aura = CharmAura(holder=holder, item=item, passive=passive)
            self._auras[aura.key] = aura
            self._applied.setdefault(aura.key, set())

    def unregister_holder(self, holder: CharacterId) -> None:
        for key in [key for key in self._auras if key[0] == holder]:
            aura = self._auras.pop(key)
            for char_id in self._applied.pop(key, set()):
                self._apply(aura, char_id, revert=True)

    def refresh(self) -> None:
        for aura in self._auras.values():
            current = self._applied[aura.key]
            wanted = self._targets_in_range(aura)
            for char_id in current - wanted:
                self._apply(aura, char_id, revert=True)
            for char_id in wanted - current:
                self._apply(aura, char_id, revert=False)
            self._applied[aura.key] = wanted

    def clear(self) -> None:
        for holder in {key[0] for key in self._auras}:
            self.unregister_holder(holder)

    def _targets_in_range(self, aura: CharmAura) -> set[CharacterId]:
        holder_char = self._context.characters.get(aura.holder)
        if holder_char is None:
            return set()
        holder_pos = self._context.find_character_position(aura.holder)
        return {
            char_id
            for char_id, char in self._context.characters.items()
            if char.faction == holder_char.faction
            and is_reachable(
                holder_pos,
                self._context.find_character_position(char_id),
                aura.item.attack_range,
            )
        }

    def _apply(self, aura: CharmAura, char_id: CharacterId, *, revert: bool) -> None:
        character = self._context.characters.get(char_id)
        if character is None:
            return
        for effect in aura.passive.effects:
            effect.apply_standing_state(character.status, revert=revert)


def charm_config_error(
    item: ItemData, passive: "PassiveSkillData | None"
) -> str | None:
    """부적 한 줄의 설정 중 조용히 무시될 조합을 찾아 경고 문구를 만든다.
    문제가 없으면 None."""
    if item.item_type is not ItemType.CHARM or not item.passive_skill_id:
        return None
    if passive is None:
        return (
            f"부적 '{item.id}'의 passive_skill_id '{item.passive_skill_id}'가"
            " '스킬_패시브' 시트에 없습니다."
        )

    ignored = [
        type(effect).__name__
        for effect in passive.effects
        if not effect.is_standing_state
    ]
    if ignored or passive.buff_mod_event is not None:
        names = ", ".join(ignored + (["buff_id"] if passive.buff_mod_event else []))
        return (
            f"부적 '{item.id}'의 패시브 '{passive.id}' 중 {names}은(는) 적용되지"
            " 않습니다 — 부적에는 범위에 있는 동안 유지되는 효과"
            "(SkillEffectFieldStatOffset, SkillEffectRevivalCountFloor)만 쓸 수"
            " 있습니다."
        )
    return None
