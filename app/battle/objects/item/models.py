import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Type

from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillEffectBase, parse_skill_effect
from battle.objects.skill.target_functions import SkillTargetRule

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass(frozen=True)
class Item:
    target_rule: SkillTargetRule
    data: "ItemData"


@dataclass(frozen=True)
class ItemData:
    """독립적인 코스트와 사거리를 가진 소비형 스킬 슬롯.

    스킬과 달리 효과는 1개이며 사거리(attack_range)를 스스로 가진다.
    효과·대상 규칙은 스킬 시스템(SkillEffectBase / SkillTargetRule)을 그대로 재사용한다.
    """

    id: str
    target_rule: str
    cost: int
    attack_range: int
    effect: SkillEffectBase
    description: str = ""
    usable_outside_battle: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, str | int]) -> "ItemData":
        effect = parse_skill_effect(data, 0)
        if effect is None:
            raise ValueError(f"아이템({data.get('id')})에 효과(effect_0)가 없습니다.")

        return ItemData(
            id=data["id"],
            target_rule=data["target_rule"],
            cost=data["cost"],
            attack_range=data["range"],
            effect=effect,
            description=data.get("description", "") or "",
            usable_outside_battle=bool(data.get("usable_outside_battle", False)),
        )

    def to_item_instance(
        self, context: "BattlefieldContext", holder: CharacterId
    ) -> Item:
        target_rule_module = importlib.import_module(
            "battle.objects.skill.target_functions"
        )
        rule: Type[SkillTargetRule] = getattr(target_rule_module, self.target_rule)
        return Item(target_rule=rule(context, holder), data=self)
