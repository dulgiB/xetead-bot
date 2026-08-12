import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Type

from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillEffectBase, parse_skill_effect
from battle.objects.skill.target_functions import SkillTargetRule
from utils.spreadsheet_bool import parse_spreadsheet_bool
from utils.spreadsheet_row import SpreadsheetRow

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
    # 스토리 진행용 키 아이템은 전투/비전투 효과 없이 소지 자체가 목적이라
    # effect_0이 비어 있을 수 있다 — None이면 사용(전투 내 [아이템] 커맨드,
    # 비전투 [사용])이 모두 명시적으로 거부된다.
    effect: Optional[SkillEffectBase]
    description: str = ""
    usable_outside_battle: bool = False

    @classmethod
    def from_dict(cls, data: SpreadsheetRow) -> "ItemData":
        effect = parse_skill_effect(data, 0)

        return ItemData(
            id=str(data["id"]),
            target_rule=str(data["target_rule"]),
            cost=int(data["cost"]),
            attack_range=int(data["range"]),
            effect=effect,
            description=str(data.get("description", "") or ""),
            usable_outside_battle=parse_spreadsheet_bool(
                data.get("usable_outside_battle", False)
            ),
        )

    def to_item_instance(
        self, context: "BattlefieldContext", holder: CharacterId
    ) -> Item:
        target_rule_module = importlib.import_module(
            "battle.objects.skill.target_functions"
        )
        rule: Type[SkillTargetRule] = getattr(target_rule_module, self.target_rule)
        return Item(target_rule=rule(context, holder), data=self)
