"""부적 아이템의 필드 효과.

부적은 **누군가 지니고 있기만 하면** 본 전투에서 발동한다. 소지자의 전투
참여를 요구하지 않는 것이 요점이다 — 요구하면 참여를 강요하는 압력이 된다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ItemType,
    ValueType,
)
from battle.objects.field_effect.models import FieldEffectSource
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectAddBuff
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import SideType
from helpers import get_test_preset
from spreadsheets.inventory import Inventory

CHARM_ID = "행운의 부적"
CHARM_EFFECT_ID = "FieldEffect"
CHARM_BUFF_ID = "FieldBuff"


def _charm_buff() -> BuffData:
    return BuffData(
        id=CHARM_BUFF_ID,
        buff_class_name="BuffAtk",
        duration_turn_value=None,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=5,
        condition_=None,
        condition_value=None,
        buff_type=BuffType.BUFF,
        description="",
    )


def _charm_effect() -> PassiveSkillData:
    return PassiveSkillData(
        id=CHARM_EFFECT_ID,
        trigger=PassiveSkillTrigger.BATTLE_START,
        target_type=PassiveSkillTargetType.FIELD_ALLY_SIDE,
        effects=[
            SkillEffectAddBuff(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=CHARM_BUFF_ID,
                buff_add_timing=None,
            )
        ],
        description="지니고 있으면 운이 좋아진다.",
    )


def _charm_item(passive_skill_id: str = CHARM_EFFECT_ID) -> ItemData:
    return ItemData(
        id=CHARM_ID,
        target_rule="",
        cost=0,
        attack_range=0,
        effect=None,
        description="지니고 있으면 운이 좋아진다.",
        item_type=ItemType.CHARM,
        passive_skill_id=passive_skill_id,
    )


def _make_context(
    inventory_counts: dict[tuple[str, str], int],
    item: ItemData | None = None,
) -> BattlefieldContext:
    ctx = BattlefieldContext(
        buff_dict={CHARM_BUFF_ID: _charm_buff()},
        skill_dict={},
        passive_skill_dict={CHARM_EFFECT_ID: _charm_effect()},
        item_dict={CHARM_ID: item if item is not None else _charm_item()},
        inventory=Inventory(dict(inventory_counts)),
    )
    ctx.add_character(
        get_test_preset("참전자"), FactionType.ALLY, BattlefieldColumnIndex(0)
    )
    ctx.add_character(
        get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
    )
    return ctx


def _has_charm_buff(ctx: BattlefieldContext, name: str) -> bool:
    return ctx.buff_container.get_buff(CharacterId(name), CHARM_BUFF_ID) is not None


class TestOwnershipTriggersTheEffect:
    def test_effect_applies_when_a_participant_owns_it(self):
        ctx = _make_context({("참전자", CHARM_ID): 1})

        ctx.on_battle_start()

        assert CHARM_EFFECT_ID in ctx.field_effects
        assert _has_charm_buff(ctx, "참전자")

    def test_effect_applies_even_if_the_owner_is_not_in_the_battle(self):
        """소지자의 전투 참여를 요구하지 않는다."""
        ctx = _make_context({("불참자", CHARM_ID): 1})

        ctx.on_battle_start()

        assert CHARM_EFFECT_ID in ctx.field_effects
        assert _has_charm_buff(ctx, "참전자")

    def test_nothing_happens_when_nobody_owns_it(self):
        ctx = _make_context({})

        ctx.on_battle_start()

        assert CHARM_EFFECT_ID not in ctx.field_effects

    def test_zero_count_does_not_count_as_owned(self):
        ctx = _make_context({("참전자", CHARM_ID): 0})

        ctx.on_battle_start()

        assert CHARM_EFFECT_ID not in ctx.field_effects

    def test_source_is_recorded_as_the_charm(self):
        ctx = _make_context({("참전자", CHARM_ID): 1})

        ctx.on_battle_start()

        effect = ctx.field_effects.get(CHARM_EFFECT_ID)
        assert effect is not None
        assert effect.source is FieldEffectSource.CHARM
        assert effect.source_detail == CHARM_ID

    def test_two_owners_apply_the_effect_once(self):
        """종류당 1개라는 전제가 시트에서 깨져도 한 번만 걸려야 한다."""
        ctx = _make_context({("참전자", CHARM_ID): 1, ("불참자", CHARM_ID): 1})

        ctx.on_battle_start()

        assert len(ctx.field_effects) == 1


class TestMisconfiguration:
    def test_charm_without_a_passive_skill_id_is_ignored(self):
        ctx = _make_context(
            {("참전자", CHARM_ID): 1}, item=_charm_item(passive_skill_id="")
        )

        ctx.on_battle_start()

        assert len(ctx.field_effects) == 0

    def test_charm_pointing_at_a_missing_effect_does_not_break_the_battle(self):
        ctx = _make_context(
            {("참전자", CHARM_ID): 1}, item=_charm_item(passive_skill_id="사라진효과")
        )

        ctx.on_battle_start()

        assert len(ctx.field_effects) == 0

    def test_non_charm_item_is_not_registered(self):
        item = ItemData(
            id=CHARM_ID,
            target_rule="",
            cost=0,
            attack_range=0,
            effect=None,
            item_type=ItemType.ETC,
            passive_skill_id=CHARM_EFFECT_ID,
        )
        ctx = _make_context({("참전자", CHARM_ID): 1}, item=item)

        ctx.on_battle_start()

        assert len(ctx.field_effects) == 0


class TestPracticeModesExcluded:
    def test_charm_does_not_apply_in_practice(self):
        ctx = PracticeBattlefieldContext(
            buff_dict={CHARM_BUFF_ID: _charm_buff()},
            skill_dict={},
            passive_skill_dict={CHARM_EFFECT_ID: _charm_effect()},
            item_dict={CHARM_ID: _charm_item()},
        )
        # 대련 컨텍스트는 인벤토리를 받지 않지만, 막는 것이 "인벤토리가 비어
        # 있어서"가 아니라 allow_field_effects임을 드러내려고 직접 채운다.
        ctx.inventory = Inventory({("대련_1", CHARM_ID): 1})
        ctx.add_character(
            get_test_preset("대련_1"), SideType.SIDE_1, BattlefieldColumnIndex(0)
        )

        ctx.on_battle_start()

        assert len(ctx.field_effects) == 0
