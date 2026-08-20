"""패시브 스킬(PassiveSkill) + 코스트 2 스킬(Cost2Skill) + 코스트 3 스킬(Cost3Skill)을
가진 캐릭터의 스킬셋이 실제 스프레드시트 행 그대로(각 데이터클래스의 from_dict()를
거쳐) 로드했을 때 의도대로 동작하는지 확인하는 통합 테스트.

캐릭터/스킬/버프 id는 실제 스프레드시트의 고유명사를 코드에 노출하지 않도록 모두
일반화한 이름(MarkStacker, PassiveSkill, Cost2Skill, Cost3Skill, Mark, MarkDrain,
MarkCounter)을 쓴다.

시나리오:
- 패시브: 기본 공격/스킬로 대미지를 줄 때마다 대상에게 2턴간 [Mark](3회까지
  적층)를 부여한다.
- 코스트 2 스킬: 공격 굴림 200% 대미지 + 대상에게 2턴간 [MarkDrain] 부여.
  [MarkDrain]은 라운드 종료마다 (대상의 [Mark] 스택 수)×5 고정 대미지를 입힌다.
- 코스트 3 스킬: 공격 굴림 300% 대미지 + 자신에게 2턴간 [MarkCounter] 부여.
  [MarkCounter]는 사거리 내의 적이 이동할 때마다(자발적/강제 이동 모두)
  (이동한 적의 [Mark] 스택 수)×(공격 굴림 70%) 대미지를 입히며, 이 반격
  자체는 [Mark]를 새로 부여하지 않는다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData, PassiveBuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from bot.battle_reply_text import format_battle_reply
from helpers import get_test_preset
from spreadsheets.inventory import Inventory


def _buff_dict() -> dict[str, BuffData]:
    """'버프' 시트의 행들."""
    return {
        "Mark": BuffData.from_dict(
            {
                "id": "Mark",
                "buff_name": "BuffStackingMark",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": "",
                "value_type_0": "",
                "condition": "",
                "condition_value": "",
                "description": "디버프. 3회까지 적층된다. 단독으로는 효과가 없다.",
                "is_debuff": True,
                "max_stack": 3,
            }
        ),
        "MarkDrain": BuffData.from_dict(
            {
                "id": "MarkDrain",
                "buff_name": "BuffDamageOverTimePerReferencedBuffStack",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": 5,
                "value_type_0": "정수",
                "condition": "",
                "condition_value": "",
                "description": "디버프. 라운드 종료마다 [Mark] 스택×5 고정 대미지를 입는다.",
                "is_debuff": True,
                "max_stack": "",
                "reference_buff_id": "Mark",
            }
        ),
        "MarkCounter": BuffData.from_dict(
            {
                "id": "MarkCounter",
                "buff_name": "BuffCounterDamageOnEnemyMove",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": 70,
                "value_type_0": "퍼센트",
                "condition": "TargetIsInRangeCondition",
                "condition_value": "",
                "description": (
                    "버프. 사거리 내의 적이 이동할 때마다(강제 이동 포함) "
                    "이동한 적의 [Mark] 스택×공격 굴림 70% 대미지를 입힌다."
                ),
                "is_debuff": False,
                "max_stack": "",
                "reference_buff_id": "Mark",
            }
        ),
    }


def _passive_buff_dict() -> dict[str, PassiveBuffData]:
    """'버프_패시브' 시트의 행 하나(대미지를 줄 때마다 [Mark] 부여 모디파이어)."""
    return {
        "PassiveBuffMod": PassiveBuffData.from_dict(
            {
                "id": "PassiveBuffMod",
                "buff_name": "BuffApplyDebuffOnDealingDamage",
                "value_0": "",
                "value_type_0": "",
                "condition": "",
                "condition_value": "",
                "description": "",
                "reference_buff_id": "Mark",
            }
        ),
    }


def _skill_dict() -> dict[str, SkillData]:
    """'스킬_캐릭터' 시트의 코스트 2/코스트 3 스킬 행 + 테스트 전용 강제 이동 스킬."""
    return {
        "Cost2Skill": SkillData.from_dict(
            {
                "id": "Cost2Skill",
                "target_rule": "SkillTargetRuleNamed",
                "target_count": 1,
                "cost": 2,
                "effect_0": "SkillEffectDamage",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "공격 굴림값",
                "value_0": 200,
                "value_type_0": "퍼센트",
                "buff_id_0": "",
                "buff_stack_cap_0": "",
                "target_override_0": "",
                "effect_1": "SkillEffectAddBuff",
                "condition_1": "",
                "condition_value_1": "",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "MarkDrain",
                "buff_stack_cap_1": "",
                "target_override_1": "",
                "effect_2": "",
                "condition_2": "",
                "condition_value_2": "",
                "value_source_2": "",
                "value_2": "",
                "value_type_2": "",
                "buff_id_2": "",
                "buff_stack_cap_2": "",
                "target_override_2": "",
                "description": (
                    "대상에게 공격 굴림 200%만큼 대미지를 입히고 2턴간 [MarkDrain]을 "
                    "부여한다."
                ),
            }
        ),
        "Cost3Skill": SkillData.from_dict(
            {
                "id": "Cost3Skill",
                "target_rule": "SkillTargetRuleNamed",
                "target_count": 1,
                "cost": 3,
                "effect_0": "SkillEffectDamage",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "공격 굴림값",
                "value_0": 300,
                "value_type_0": "퍼센트",
                "buff_id_0": "",
                "buff_stack_cap_0": "",
                "target_override_0": "",
                "effect_1": "SkillEffectAddBuff",
                "condition_1": "",
                "condition_value_1": "",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "MarkCounter",
                "buff_stack_cap_1": "",
                "target_override_1": "자신",
                "effect_2": "",
                "condition_2": "",
                "condition_value_2": "",
                "value_source_2": "",
                "value_2": "",
                "value_type_2": "",
                "buff_id_2": "",
                "buff_stack_cap_2": "",
                "target_override_2": "",
                "description": (
                    "대상에게 공격 굴림 300%만큼 대미지를 입히고 자신에게 2턴간 "
                    "[MarkCounter]를 부여한다."
                ),
            }
        ),
        "ForceMoveSkill": SkillData.from_dict(
            {
                "id": "ForceMoveSkill",
                "target_rule": "SkillTargetRuleNamed",
                "target_count": 1,
                "cost": 1,
                "effect_0": "SkillEffectMove",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "고정값",
                "value_0": 3,
                "value_type_0": "",
                "buff_id_0": "",
                "buff_stack_cap_0": "",
                "target_override_0": "",
                "effect_1": "",
                "condition_1": "",
                "condition_value_1": "",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "",
                "buff_stack_cap_1": "",
                "target_override_1": "",
                "effect_2": "",
                "condition_2": "",
                "condition_value_2": "",
                "value_source_2": "",
                "value_2": "",
                "value_type_2": "",
                "buff_id_2": "",
                "buff_stack_cap_2": "",
                "target_override_2": "",
                "description": "테스트용. 대상을 4열로 강제 이동시킨다(대미지 없음).",
            }
        ),
    }


def _passive_skill_dict() -> dict[str, PassiveSkillData]:
    """'스킬_패시브' 시트의 패시브 스킬 행."""
    return {
        "PassiveSkill": PassiveSkillData.from_dict(
            {
                "id": "PassiveSkill",
                "trigger": "행동 시",
                "target_type": "자신",
                "buff_id": "PassiveBuffMod",
                "description": (
                    "기본 공격이나 스킬로 대미지를 줄 때마다 대상에게 2턴간 [Mark]를 "
                    "부여한다."
                ),
            },
            _passive_buff_dict(),
        ),
    }


def _make_context(
    *,
    milestone_n: int = 0,
    item_dict: dict[str, ItemData] | None = None,
    inventory: Inventory | None = None,
) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict=_buff_dict(),
        skill_dict=_skill_dict(),
        passive_skill_dict=_passive_skill_dict(),
        item_dict=item_dict,
        inventory=inventory,
        milestone_n=milestone_n,
    )


def _setup_ally_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


def _setup_enemy_pre_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


class TestPassiveSkill:
    """패시브: 대미지를 줄 때마다 대상에게 [Mark]를 부여한다. 맞을 때는 부여하지
    않는다(방향성)."""

    def test_grants_mark_to_target_on_basic_attack(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("MarkStacker")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("MarkStacker", atk=100, passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(parse_character_command(caster, "[공격/적군]", ctx))

        assert ctx.get_buff_stack(target, "Mark") == 1
        assert ctx.get_buff_stack(caster, "Mark") == 0

    def test_does_not_grant_mark_when_damage_dealt_via_item(self):
        """ "기본 공격/스킬로"라는 설명대로, 대미지를 주는 아이템 사용은
        직접 행동이 아니므로 [Mark]가 부여되면 안 된다."""
        item_bomb = ItemData(
            id="폭탄",
            target_rule="SkillTargetRuleNamed",
            cost=1,
            attack_range=1,
            effect=SkillEffectDamage(
                ValueSourceType.FIXED, 50, ValueType.INTEGER, None, None
            ),
        )
        ctx = _make_context(
            item_dict={"폭탄": item_bomb},
            inventory=Inventory({("MarkStacker", "폭탄"): 1}),
        )
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("MarkStacker")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("MarkStacker", atk=100, passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(parse_character_command(caster, "[폭탄/적군]", ctx))

        assert ctx.characters[target].status.curr_hp == 1000 - 50
        assert ctx.get_buff_stack(target, "Mark") == 0

    def test_does_not_grant_mark_when_holder_is_hit(self):
        """홀더가 맞기만 했을 때는(홀더가 공격자가 아닐 때) [Mark]가 부여되지 않는다."""
        ctx = _make_context()
        manager = RoundManager(ctx)
        manager.process_command(
            ChangePhaseCommand(
                type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
            )
        )
        holder = CharacterId("MarkStacker")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset("MarkStacker", passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", atk=10),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(
            parse_character_command(enemy, "[공격/MarkStacker]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.get_buff_stack(holder, "Mark") == 0
        assert ctx.get_buff_stack(enemy, "Mark") == 0

    def test_mark_stack_caps_at_three(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("MarkStacker")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset(
                "MarkStacker", atk=1, max_cost=10, passive_skill_id="PassiveSkill"
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        for _ in range(4):
            manager.process_command(parse_character_command(caster, "[공격/적군]", ctx))

        assert ctx.get_buff_stack(target, "Mark") == 3

    def test_mark_grant_is_bundled_into_the_attack_reply(self):
        """[Mark] 부여는 buff_add_data_list 경로를 거치지 않고 buff_container를
        직접 호출하므로, extra_log_entries를 통해 같은 공격 답글 블록에
        묶여 나와야 한다."""
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("MarkStacker")
        ctx.add_character(
            get_test_preset("MarkStacker", atk=100, passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        before = len(ctx.results)
        manager.process_command(parse_character_command(caster, "[공격/적군]", ctx))
        reply, calc = format_battle_reply(ctx, caster, ctx.results[before:])

        assert reply == ("▹ 적군 | -100 → 900/1000\n▹ 적군 | [Mark]×1 부여 → 최종 1")
        assert calc == "【공격 ▸ 적군】\n▹ 적군 | (100 + 0[0d6]) → -100"


class TestCost2Skill:
    """코스트 2 스킬: 공격 굴림 200% 대미지 + 대상에게 2턴간 [MarkDrain] 부여."""

    def test_deals_damage_and_grants_mark_drain(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("MarkStacker")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("MarkStacker", atk=100, skill_1_id="Cost2Skill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost2Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 200
        assert ctx.buff_container.get_buff(target, "MarkDrain") is not None


class TestMarkDrainBuff:
    """[MarkDrain]: 라운드 종료마다 (대상의 [Mark] 스택 수)×5 고정 대미지.
    턴 차감 전 스택 기준으로 계산되므로 마지막 턴에도 정상 발동한다."""

    def test_deals_damage_based_on_mark_stack_at_round_end(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("MarkStacker"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="MarkStacker", applied_to="적군", buff_id="Mark", stack=3
            )
        )
        ctx.buff_container.add(
            _buff_add(given_by="MarkStacker", applied_to="적군", buff_id="MarkDrain")
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 15

    def test_still_deals_damage_on_the_final_turn_before_expiry(self):
        """[MarkDrain]의 남은 턴이 이번 라운드로 끝나는 마지막 턴이어도, 턴이
        차감되어 버프가 제거되기 전에 스택 기반 대미지가 먼저 적용돼야 한다."""
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("MarkStacker"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="MarkStacker", applied_to="적군", buff_id="Mark", stack=3
            )
        )
        ctx.buff_container.add(
            _buff_add(given_by="MarkStacker", applied_to="적군", buff_id="MarkDrain")
        )
        # 이번 라운드가 [MarkDrain]의 마지막 턴이 되도록 강제로 조정한다.
        mark_drain = ctx.buff_container.get_buff(target, "MarkDrain")
        mark_drain.duration.remaining_turns = 1

        hp_before = ctx.characters[target].status.curr_hp
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 15
        assert ctx.buff_container.get_buff(target, "MarkDrain") is None

    def test_round_end_damage_does_not_retrigger_the_passive(self):
        """[MarkDrain]의 라운드 종료 대미지는 given_by(부여자)를 attacker_id로
        기록하지만, 그렇다고 given_by가 "대미지를 줄 때마다" 발동하는 패시브를
        다시 유발해서는 안 된다 — 그러면 라운드마다 [Mark] 스택이 저절로
        재적립되는 순환이 생긴다."""
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("MarkStacker", passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="MarkStacker", applied_to="적군", buff_id="Mark", stack=2
            )
        )
        ctx.buff_container.add(
            _buff_add(given_by="MarkStacker", applied_to="적군", buff_id="MarkDrain")
        )

        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

        assert ctx.get_buff_stack(target, "Mark") == 2


class TestCost3Skill:
    """코스트 3 스킬: 공격 굴림 300% 대미지 + 자신에게 2턴간 [MarkCounter] 부여."""

    def test_deals_damage_and_grants_mark_counter_to_self(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("MarkStacker")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("MarkStacker", atk=100, skill_1_id="Cost3Skill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 300
        assert ctx.buff_container.get_buff(caster, "MarkCounter") is not None


class TestMarkCounterBuff:
    """[MarkCounter]: 사거리 내의 적이 이동할 때마다(자발/강제 모두) 이동한 적의
    [Mark] 스택×공격 굴림 70% 대미지를 입힌다. 이 반격은 [Mark]를 새로 부여하지
    않는다."""

    def _setup(self, *, phase: RoundPhaseType = RoundPhaseType.ENEMY_PRE_ACTION):
        ctx = _make_context()
        manager = (
            _setup_enemy_pre_phase(ctx)
            if phase == RoundPhaseType.ENEMY_PRE_ACTION
            else _setup_ally_phase(ctx)
        )
        caster = CharacterId("MarkStacker")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset(
                "MarkStacker",
                atk=100,
                attack_range=5,
                passive_skill_id="PassiveSkill",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="MarkStacker", applied_to="적군", buff_id="Mark", stack=2
            )
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="MarkStacker", applied_to="MarkStacker", buff_id="MarkCounter"
            )
        )
        return ctx, manager, caster, enemy

    def test_triggers_on_voluntary_move_within_range(self):
        ctx, manager, caster, enemy = self._setup()

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[이동/2열]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        # 스택 2 × (공격 굴림 100 × 0.7) = 140.
        assert hp_before - hp_after == 140
        assert ctx.get_buff_stack(enemy, "Mark") == 2

    def test_triggers_on_forced_move_via_skill(self):
        ctx, manager, caster, enemy = self._setup(phase=RoundPhaseType.ALLY_ACTION)
        ctx.add_character(
            get_test_preset("동료", skill_1_id="ForceMoveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(
            parse_character_command(CharacterId("동료"), "[ForceMoveSkill/적군]", ctx)
        )
        hp_after = ctx.characters[enemy].status.curr_hp

        assert hp_before - hp_after == 140
        assert ctx.get_buff_stack(enemy, "Mark") == 2

    def test_does_not_trigger_when_out_of_range(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset(
                "MarkStacker", atk=100, attack_range=1, passive_skill_id="PassiveSkill"
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(6),
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="MarkStacker", applied_to="적군", buff_id="Mark", stack=2
            )
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="MarkStacker", applied_to="MarkStacker", buff_id="MarkCounter"
            )
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[이동/5열]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        assert hp_before == hp_after

    def test_no_damage_and_no_trigger_when_target_has_no_mark_stack(self):
        """[Mark] 스택이 0이면 대미지가 발생하지 않을 뿐 아니라, 답글에도
        이동 결과만 남고 대미지 항목 자체가 생기지 않아야 한다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset(
                "MarkStacker", atk=100, attack_range=5, passive_skill_id="PassiveSkill"
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="MarkStacker", applied_to="MarkStacker", buff_id="MarkCounter"
            )
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        before = len(ctx.results)
        manager.process_command(parse_character_command(enemy, "[이동/2열]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp
        reply, calc = format_battle_reply(ctx, enemy, ctx.results[before:])

        assert hp_before == hp_after
        assert reply == "▹ 적군 | 2열로 이동"
        assert calc == ""

    def test_reply_decomposes_coefficient_and_stack_with_source_labels(self):
        """반격 계산식은 (버프 계수 × 스택)을 미리 곱한 값 하나가 아니라, 각각
        어디서 온 배율인지 알 수 있도록 "× (a × b)" 형태로 분해해서 보여줘야
        한다."""
        ctx, manager, caster, enemy = self._setup()

        before = len(ctx.results)
        manager.process_command(parse_character_command(enemy, "[이동/2열]", ctx))
        reply, calc = format_battle_reply(ctx, enemy, ctx.results[before:])

        assert reply == (
            "▹ 적군 | 2열로 이동\n▹ 적군 | -140 → 860/1000 [MarkCounter: MarkStacker]"
        )
        assert calc == (
            "【이동 ▸ 2열】\n"
            "▹ 적군 | (100 + 0[0d6]) × (0.7[MarkCounter 계수] × 2[Mark]) → -140"
        )


def _buff_add(*, given_by: str, applied_to: str, buff_id: str, stack: int = 1):
    return BuffAddData(
        given_by=CharacterId(given_by),
        applied_to=CharacterId(applied_to),
        buff_id=buff_id,
        stack_value=stack,
    )
