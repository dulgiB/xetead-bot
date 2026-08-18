import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Type

from battle.objects.define import ItemType
from battle.objects.models import CharacterId
from battle.objects.skill.models import SkillEffectBase, parse_skill_effect
from battle.objects.skill.target_functions import SkillTargetRule
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
    # 소지 자체가 목적인 아이템(item_type="기타")은 전투/비전투 효과가 없어
    # effect_0이 비어 있을 수 있다 — None이면 사용(전투 내 [아이템] 커맨드,
    # 비전투 [사용])이 모두 명시적으로 거부된다. "비전투 소모품"도 effect가
    # 항상 None이지만, 그쪽은 item_type 자체로 비전투 전용 로직을 탄다.
    effect: Optional[SkillEffectBase]
    description: str = ""
    item_type: ItemType = ItemType.BATTLE_CONSUMABLE

    @classmethod
    def from_dict(cls, data: SpreadsheetRow) -> "ItemData":
        effect = parse_skill_effect(data, 0)
        item_type = ItemType(str(data["item_type"]))

        # "기타"(사용 불가)/"부적"(미구현 패시브 슬롯)/"비전투 소모품"(자신
        # 전용, 아이템별 전용 로직으로 처리)은 전투 슬롯(대상 규칙·코스트·
        # 사거리)이 의미가 없으므로 비워 둘 수 있다 — 그 외 item_type은
        # 기존과 동일하게 필수로 요구한다.
        if item_type in (ItemType.ETC, ItemType.CHARM, ItemType.NONCOMBAT_CONSUMABLE):
            target_rule = str(data.get("target_rule", "") or "")
            cost = int(data.get("cost") or 0)
            attack_range = int(data.get("range") or 0)
        else:
            target_rule = str(data["target_rule"])
            cost = int(data["cost"])
            attack_range = int(data["range"])

        return ItemData(
            id=str(data["id"]),
            target_rule=target_rule,
            cost=cost,
            attack_range=attack_range,
            effect=effect,
            description=str(data.get("description", "") or ""),
            item_type=item_type,
        )

    def to_item_instance(
        self, context: "BattlefieldContext", holder: CharacterId
    ) -> Item:
        target_rule_module = importlib.import_module(
            "battle.objects.skill.target_functions"
        )
        rule: Type[SkillTargetRule] = getattr(target_rule_module, self.target_rule)
        return Item(target_rule=rule(context, holder), data=self)
