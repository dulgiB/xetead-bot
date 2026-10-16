import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from battle.objects.buff.buff_base import BuffBase, BuffDurationCounter
from battle.objects.buff.buff_events import BuffEvent, BuffEventCalculatePriority
from battle.objects.define import BuffApplyTiming, BuffType, ItemType
from battle.objects.item.models import ItemData
from battle.objects.models import BuffUid, CharacterId
from battle.objects.passive_skill.models import PassiveSkillData

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext

logger = logging.getLogger(__name__)

# 라운드 시작에 걸어 그 라운드 종료 차감에서 빠진다.
CHARM_BUFF_DURATION_TURNS = 1


@dataclass(frozen=True)
class CharmAura:
    """전장에 있는 소지자 한 명이 지닌 부적 하나."""

    holder: CharacterId
    item: ItemData
    passive: PassiveSkillData

    @property
    def key(self) -> tuple[CharacterId, str]:
        return (self.holder, self.item.id)

    @property
    def label(self) -> str:
        return f"{self.item.id}[{self.holder.name}]"


@dataclass(frozen=True)
class _CharmBuffEvent(BuffEvent):
    """부적 버프는 이벤트로 하는 일이 없다 — 효과는 걸려 있는 동안
    CombatStats에 얹힌 상태(on_added/on_removed)로만 나타난다."""

    @property
    def priority(self) -> BuffEventCalculatePriority:
        return BuffEventCalculatePriority.NORMAL

    def apply(self, holder, attacker_or_target, calculator, effect_seq_number) -> None:
        return None


class CharmBuff(BuffBase):
    """라운드 시작 때 부적 범위 안의 캐릭터에게 거는 1턴짜리 버프.

    "버프" 시트에 행이 없다 — 내용은 부적의 패시브(상시 상태 효과)이고,
    걸려 있는 동안만 그 상태를 CombatStats에 얹는다. 지속시간이 끝나거나
    대상이 빠지는 등 어떤 경로로든 컨테이너에서 빠지면 되돌린다.

    버프/디버프 집계(디버프 일괄 제거, 디버프 보유 조건 등)에 잡히지
    않도록 NEUTRAL로 둔다 — 부적은 원래 버프가 아니었고, 부활 하한처럼
    이득과 대가가 함께 있는 효과도 있다.
    """

    ID_PREFIX = "부적:"

    def __init__(self, aura: CharmAura, applied_to: CharacterId) -> None:
        # BuffData 없이 만든다(_create_bare와 같은 이유) — 필드를 직접 채운다.
        self.aura = aura
        self.id = f"{self.ID_PREFIX}{aura.item.id}"
        self.given_by = aura.holder
        self.applied_to = applied_to
        self.uid = BuffUid(aura.holder, applied_to, self.id)
        self.applied_at = 0
        self.value = 0
        self.value_2 = 0
        self.value_type = None
        self.duration = BuffDurationCounter(CHARM_BUFF_DURATION_TURNS, None, None)
        self.condition = None
        self.buff_type = BuffType.NEUTRAL
        self.max_stack = None
        self.stack_count = 1
        self.reference_buff_id = None

    @property
    def timing(self) -> BuffApplyTiming:
        # 이벤트가 아무 일도 하지 않으므로 어느 타이밍이든 결과는 같다.
        return BuffApplyTiming.ON_ROUND_START

    def create_event(self) -> BuffEvent:
        return _CharmBuffEvent(condition=None)

    def display_id_label(self) -> str:
        return self.aura.label

    def get_description(self, context: "BattlefieldContext") -> str:
        return self.aura.passive.description

    def on_added(self, context: "BattlefieldContext") -> None:
        self._apply(context, revert=False)

    def on_removed(self, context: "BattlefieldContext") -> None:
        self._apply(context, revert=True)

    def _apply(self, context: "BattlefieldContext", *, revert: bool) -> None:
        character = context.characters.get(self.applied_to)
        if character is None:
            return
        for effect in self.aura.passive.effects:
            effect.apply_standing_state(character.status, revert=revert)


class CharmAuraContainer:
    """라운드 시작 때 부적 사거리 안의 같은 진영 캐릭터(소지자 포함)에게
    부적의 효과를 1턴짜리 버프(CharmBuff)로 건다.

    사거리는 소지자의 공격 사거리가 아니라 "아이템" 시트의 `range`다.
    범위는 **라운드 시작 시점의 위치**로 정한다. 라운드 도중 위치를 따라
    범위를 바꾸면, 라운드 시작에 정해지는 턴당 코스트와 라운드 후반에
    정산되는 받는 대미지가 서로 다른 범위를 보게 된다 — 코스트 보너스는
    못 받았는데 대미지 증가만 떠안는 캐릭터가 생긴다.

    효과는 상시 상태(SkillEffectBase.is_standing_state)만 쓴다. 버프가 걸려
    있는 동안 CombatStats에 얹고, 버프가 빠질 때 되돌린다.
    """

    def __init__(self, context: "BattlefieldContext") -> None:
        self._context = context
        self._auras: dict[tuple[CharacterId, str], CharmAura] = {}

    def as_list(self) -> list[CharmAura]:
        return list(self._auras.values())

    def register_holder(self, holder: CharacterId) -> None:
        """holder가 지닌 부적을 모두 등록한다. 효과는 다음 라운드 시작부터
        건다."""
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

    def unregister_holder(self, holder: CharacterId) -> None:
        """holder의 부적 등록만 내린다. 이번 라운드에 이미 건 버프는 다른
        버프처럼 남은 지속시간 동안 유지된다."""
        for key in [key for key in self._auras if key[0] == holder]:
            del self._auras[key]

    def grant_round_buffs(self) -> None:
        """라운드 시작: 지금 위치 기준으로 범위 안의 대상에게 버프를 건다.
        코스트 회복보다 먼저 불러야 턴당 코스트 보너스가 이번 라운드에
        반영된다."""
        for aura in self._auras.values():
            for char_id in self._targets_in_range(aura):
                self._context.buff_container.add_unlisted(CharmBuff(aura, char_id))

    def restore_buff(
        self,
        holder: CharacterId,
        item_id: str,
        applied_to: CharacterId,
        remaining_turns: int | None,
    ) -> bool:
        """재기동 복원: 스냅샷에 남은 부적 버프를 되살린다. 위치를 다시 보지
        않는다 — 그 라운드 시작 때 정한 범위를 그대로 이어받아야 한다.
        소지자의 부적이 더는 등록돼 있지 않으면 False."""
        aura = self._auras.get((holder, item_id))
        if aura is None or applied_to not in self._context.characters:
            return False
        buff = CharmBuff(aura, applied_to)
        if remaining_turns is not None:
            buff.duration.remaining_turns = remaining_turns
        self._context.buff_container.add_unlisted(buff)
        return True

    def clear(self) -> None:
        self._auras.clear()

    def _targets_in_range(self, aura: CharmAura) -> set[CharacterId]:
        holder_char = self._context.characters.get(aura.holder)
        if holder_char is None:
            return set()
        return {
            char_id
            for char_id, char in self._context.characters.items()
            if char.faction == holder_char.faction
            and self._context.can_reach(aura.holder, char_id, aura.item.attack_range)
        }


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
            " 않습니다 — 부적에는 버프가 걸린 라운드 동안 유지되는 효과"
            "(SkillEffectFieldStatOffset, SkillEffectRevivalCountFloor)만 쓸 수"
            " 있습니다."
        )
    return None
