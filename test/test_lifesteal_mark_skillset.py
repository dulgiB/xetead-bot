"""패시브 스킬(PassiveSkill) + 코스트 2 스킬(Cost2Skill) + 코스트 3 스킬(Cost3Skill)을
가진 캐릭터의 스킬셋이 실제 스프레드시트 행 그대로(각 데이터클래스의 from_dict()를
거쳐) 로드했을 때 의도대로 동작하는지 확인하는 통합 테스트.

캐릭터/스킬/버프 id는 실제 스프레드시트의 고유명사를 코드에 노출하지 않도록
모두 일반화한 이름(Vampire, PassiveSkill, Cost2Skill, Cost3Skill, 스택_테스트,
받는대미지증가_테스트, 노출_테스트, 코스트감소_테스트)을 쓴다.

스킬셋 개요:
- 패시브: 대미지를 줄 때마다 그 대미지의 20%만큼 자신을 회복시키고, 회복량이
  5 이상이거나 대상이 아군이면 3턴간 [스택_테스트]를 1스택 얻는다
  (BuffHealAndBuffStackOnDealingDamage).
- 코스트 2: 열 대상 전원에게 2턴간 [노출_테스트]를 부여하고, 자신에게
  [스택_테스트]가 있다면 추가로 그 스택 수×10%를 스냅샷한 [받는대미지증가_테스트]도
  2턴간 함께 부여한다(SkillEffectAddBuffWithReferencedStackValue).
- 코스트 3: 대상에게 공격 굴림 300% 대미지. 대상이 [노출_테스트]를 보유하고
  아직 [받는대미지증가_테스트]가 없으면 그 버프를 스냅샷 부여하고, 이미
  [받는대미지증가_테스트]가 있다면 대신 [코스트감소_테스트](다음 라운드
  코스트 1 감소)를 부여한다.
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
    CombatStatType,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.item.models import ItemData
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset
from spreadsheets.inventory import Inventory


def _buff_dict() -> dict[str, BuffData]:
    """'버프' 시트의 스택_테스트/받는대미지증가_테스트/노출_테스트/코스트감소_테스트 행."""
    return {
        "스택_테스트": BuffData.from_dict(
            {
                "id": "스택_테스트",
                "buff_name": "BuffStackingMark",
                "duration_turn_value": 3,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_type": "",
                "value": "",
                "condition": "",
                "condition_value": "",
                "is_debuff": False,
                "description": "패시브로 쌓이는 순수 적층 마커.",
                "max_stack": 3,
            }
        ),
        "받는대미지증가_테스트": BuffData.from_dict(
            {
                "id": "받는대미지증가_테스트",
                # 노출_테스트와 동시에 걸릴 수 있으므로 BuffUid 충돌을 피하려면
                # BuffReceivedDamage와 별도 클래스여야 한다.
                "buff_name": "BuffReceivedDamageMark",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_type": "퍼센트",
                # 스킬 효과가 항상 value_override로 덮어쓰므로 시트값은 쓰이지 않는다.
                "value": 0,
                "condition": "",
                "condition_value": "",
                "is_debuff": True,
                "description": "받는 대미지가 (홀더의 [스택_테스트] 스택 수)×10%만큼 증가.",
            }
        ),
        "노출_테스트": BuffData.from_dict(
            {
                "id": "노출_테스트",
                "buff_name": "BuffReceivedDamage",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_type": "퍼센트",
                "value": 10,
                "condition": "",
                "condition_value": "",
                "is_debuff": True,
                "description": "받는 대미지 10% 증가.",
            }
        ),
        "코스트감소_테스트": BuffData.from_dict(
            {
                "id": "코스트감소_테스트",
                "buff_name": "BuffReduceCostNextRound",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_type": "정수",
                "value": 1,
                "condition": "",
                "condition_value": "",
                "is_debuff": True,
                "description": "다음 라운드 시작 시 코스트 1 감소.",
            }
        ),
    }


def _passive_buff_dict() -> dict[str, PassiveBuffData]:
    """'버프_패시브' 시트의 행 하나(대미지의 20% 자가 회복 + 조건부 스택 부여)."""
    return {
        "생명흡수_테스트": PassiveBuffData.from_dict(
            {
                "id": "생명흡수_테스트",
                "buff_name": "BuffHealAndBuffStackOnDealingDamage",
                "value": 20,
                "value_type": "퍼센트",
                "condition": "",
                "condition_value": "",
                "reference_buff_id": "스택_테스트",
            }
        ),
    }


def _skill_dict() -> dict[str, SkillData]:
    return {
        "Cost2Skill": SkillData.from_dict(
            {
                "id": "Cost2Skill",
                "target_rule": "SkillTargetRuleColumn",
                "target_count": 1,
                "cost": 2,
                "effect_0": "SkillEffectAddBuff",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "노출_테스트",
                "buff_stack_cap_0": "",
                "target_override_0": "",
                "effect_1": "SkillEffectAddBuffWithReferencedStackValue",
                "condition_1": "",
                "condition_value_1": "",
                "value_source_1": "",
                "value_1": 10,
                "value_type_1": "퍼센트",
                "buff_id_1": "받는대미지증가_테스트",
                "reference_buff_id_1": "스택_테스트",
                "required_target_buff_id_1": "",
                "buff_stack_cap_1": "",
                "target_override_1": "",
                "description": (
                    "사거리 내 열 하나를 지정해 그 열의 모든 적에게 2턴간 "
                    "[노출_테스트]를 부여한다. 자신에게 [스택_테스트]가 있다면 "
                    "추가로 그 스택 수×10%만큼 받는 대미지가 증가하는 "
                    "[받는대미지증가_테스트]도 2턴간 함께 부여한다."
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
                "effect_1": "SkillEffectAddBuffWithReferencedStackValue",
                "condition_1": "",
                "condition_value_1": "",
                "value_source_1": "",
                "value_1": 10,
                "value_type_1": "퍼센트",
                "buff_id_1": "받는대미지증가_테스트",
                "reference_buff_id_1": "스택_테스트",
                "required_target_buff_id_1": "노출_테스트",
                "buff_stack_cap_1": "",
                "target_override_1": "",
                "effect_2": "SkillEffectAddBuffIfTargetHasReferencedBuff",
                "condition_2": "",
                "condition_value_2": "",
                "value_source_2": "",
                "value_2": "",
                "value_type_2": "",
                "buff_id_2": "코스트감소_테스트",
                "reference_buff_id_2": "받는대미지증가_테스트",
                "buff_stack_cap_2": "",
                "target_override_2": "",
                "description": (
                    "대상에게 공격 굴림 300%만큼 대미지를 입힌다. 대상에게 "
                    "[노출_테스트]가 있고 [받는대미지증가_테스트]가 없다면 그 "
                    "버프를 부여하고, 이미 있다면 대신 대상에게 "
                    "[코스트감소_테스트]를 부여한다."
                ),
            }
        ),
    }


def _passive_skill_dict(
    passive_buff_dict: dict[str, PassiveBuffData],
) -> dict[str, PassiveSkillData]:
    return {
        "PassiveSkill": PassiveSkillData.from_dict(
            {
                "id": "PassiveSkill",
                "trigger": "행동 시",
                "target_type": "자신",
                "buff_id": "생명흡수_테스트",
                "description": (
                    "대미지를 줄 때마다 그 대미지의 20%만큼 자신을 회복시킨다. "
                    "회복량이 5 이상이거나 대상이 아군이라면 3턴간 [스택_테스트]를 "
                    "1스택 얻는다(최대 3스택)."
                ),
            },
            passive_buff_dict,
        ),
    }


def _make_context(
    *,
    milestone_n: int = 0,
    item_dict: dict[str, ItemData] | None = None,
    inventory: Inventory | None = None,
) -> BattlefieldContext:
    passive_buff_dict = _passive_buff_dict()
    return BattlefieldContext(
        buff_dict=_buff_dict(),
        skill_dict=_skill_dict(),
        passive_skill_dict=_passive_skill_dict(passive_buff_dict),
        item_dict=item_dict,
        inventory=inventory,
        milestone_n=milestone_n,
    )


def _setup_enemy_pre_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


def _setup_ally_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


class TestPassiveSkill:
    """패시브 스킬: 대미지의 20% 자가 회복 + 조건부 [스택_테스트] 부여."""

    def test_heal_and_stack_gained_when_heal_meets_threshold(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        vampire = CharacterId("Vampire")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset(
                "Vampire",
                atk=100,
                initial_hp=100,
                max_hp=200,
                passive_skill_id="PassiveSkill",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=200),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(parse_character_command(vampire, "[공격/적군]", ctx))

        # 대미지 100 -> 회복 20(=100*0.2, 임계값 5 이상) -> 스택 1.
        assert ctx.characters[enemy].status.curr_hp == 200 - 100
        assert ctx.characters[vampire].status.curr_hp == 100 + 20
        assert ctx.get_buff_stack(vampire, "스택_테스트") == 1

    def test_no_heal_or_stack_when_damage_dealt_via_item(self):
        """패시브는 "대미지를 줄 때마다"를 직접 공격/스킬로 한정한다 —
        대미지를 주는 아이템을 사용해도 회복/스택이 발동하면 안 된다."""
        item_bomb = ItemData(
            id="폭탄",
            target_rule="SkillTargetRuleNamed",
            cost=1,
            attack_range=1,
            effect=SkillEffectDamage(
                ValueSourceType.FIXED, 100, ValueType.INTEGER, None, None
            ),
        )
        ctx = _make_context(
            item_dict={"폭탄": item_bomb},
            inventory=Inventory({("Vampire", "폭탄"): 1}),
        )
        manager = _setup_ally_phase(ctx)
        vampire = CharacterId("Vampire")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset(
                "Vampire",
                atk=100,
                initial_hp=100,
                max_hp=200,
                passive_skill_id="PassiveSkill",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=200), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(parse_character_command(vampire, "[폭탄/적군]", ctx))

        # 대미지 100은 그대로 들어가지만, 아이템으로 준 대미지라 회복도
        # 스택도 발동하지 않아야 한다.
        assert ctx.characters[enemy].status.curr_hp == 200 - 100
        assert ctx.characters[vampire].status.curr_hp == 100
        assert ctx.get_buff_stack(vampire, "스택_테스트") == 0

    def test_no_stack_when_heal_below_threshold_and_target_is_enemy(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        vampire = CharacterId("Vampire")
        ctx.add_character(
            get_test_preset(
                "Vampire",
                atk=20,
                initial_hp=100,
                max_hp=200,
                passive_skill_id="PassiveSkill",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=200),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(parse_character_command(vampire, "[공격/적군]", ctx))

        # 대미지 20 -> 회복 4(<5) -> 대상이 적이므로 스택 없음.
        assert ctx.characters[vampire].status.curr_hp == 100 + 4
        assert ctx.get_buff_stack(vampire, "스택_테스트") == 0

    def test_stack_gained_regardless_of_heal_when_target_is_ally(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        vampire = CharacterId("Vampire")
        ally = CharacterId("아군")
        ctx.add_character(
            get_test_preset(
                "Vampire",
                atk=20,
                initial_hp=100,
                max_hp=200,
                passive_skill_id="PassiveSkill",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군", max_hp=200),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )

        # 기본 공격은 진영 검증이 없어 아군도 대상으로 지정할 수 있다.
        manager.process_command(parse_character_command(vampire, "[공격/아군]", ctx))

        assert ctx.characters[ally].status.curr_hp == 200 - 20
        # 회복 4(<5)여도 대상이 아군이므로 스택을 얻는다.
        assert ctx.get_buff_stack(vampire, "스택_테스트") == 1


class TestCost2Skill:
    """코스트 2 스킬: 열 전원에게 [노출_테스트] + 홀더 [스택_테스트] 보유 시
    추가로 스택 수 기반 [받는대미지증가_테스트]."""

    def _make_ready_context(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        vampire = CharacterId("Vampire")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Vampire", skill_1_id="Cost2Skill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        return ctx, manager, vampire, enemy

    def test_only_expose_granted_when_holder_lacks_stack_buff(self):
        ctx, manager, vampire, enemy = self._make_ready_context()

        manager.process_command(
            parse_character_command(vampire, "[Cost2Skill/1열]", ctx)
        )

        assert ctx.get_buff_instance(enemy, "노출_테스트") is not None
        assert ctx.get_buff_instance(enemy, "받는대미지증가_테스트") is None

    def test_snapshot_debuff_also_granted_when_holder_has_stack_buff(self):
        ctx, manager, vampire, enemy = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(
                given_by=vampire,
                applied_to=vampire,
                buff_id="스택_테스트",
                stack_value=2,
            )
        )

        manager.process_command(
            parse_character_command(vampire, "[Cost2Skill/1열]", ctx)
        )

        assert ctx.get_buff_instance(enemy, "노출_테스트") is not None
        granted = ctx.get_buff_instance(enemy, "받는대미지증가_테스트")
        assert granted is not None
        assert granted.value == 20  # 2스택 × 10%


class TestCost3Skill:
    """코스트 3 스킬: 대미지 + [노출_테스트]/[받는대미지증가_테스트] 상태에
    따른 분기(스냅샷 디버프 부여 vs 다음 라운드 코스트 감소)."""

    def _make_ready_context(self, *, holder_stack: int = 0):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        vampire = CharacterId("Vampire")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Vampire", atk=10, skill_1_id="Cost3Skill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=500),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        if holder_stack:
            ctx.buff_container.add(
                BuffAddData(
                    given_by=vampire,
                    applied_to=vampire,
                    buff_id="스택_테스트",
                    stack_value=holder_stack,
                )
            )
        return ctx, manager, vampire, target

    def test_damage_only_when_target_lacks_expose(self):
        ctx, manager, vampire, target = self._make_ready_context(holder_stack=3)
        hp_before = ctx.characters[target].status.curr_hp

        manager.process_command(
            parse_character_command(vampire, "[Cost3Skill/적군]", ctx)
        )

        assert hp_before - ctx.characters[target].status.curr_hp == 30  # atk 10 * 300%
        assert ctx.get_buff_instance(target, "받는대미지증가_테스트") is None
        assert ctx.get_buff_instance(target, "코스트감소_테스트") is None

    def test_snapshot_debuff_granted_when_target_has_expose_but_not_yet_marked(self):
        ctx, manager, vampire, target = self._make_ready_context(holder_stack=3)
        ctx.buff_container.add(
            BuffAddData(given_by=vampire, applied_to=target, buff_id="노출_테스트")
        )

        manager.process_command(
            parse_character_command(vampire, "[Cost3Skill/적군]", ctx)
        )

        granted = ctx.get_buff_instance(target, "받는대미지증가_테스트")
        assert granted is not None
        assert granted.value == 30  # 3스택 × 10%
        assert ctx.get_buff_instance(target, "코스트감소_테스트") is None

    def test_cost_reduction_granted_and_applied_next_round_when_already_marked(self):
        ctx, manager, vampire, target = self._make_ready_context(holder_stack=1)
        ctx.buff_container.add(
            BuffAddData(given_by=vampire, applied_to=target, buff_id="노출_테스트")
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=vampire, applied_to=target, buff_id="받는대미지증가_테스트"
            )
        )

        manager.process_command(
            parse_character_command(vampire, "[Cost3Skill/적군]", ctx)
        )

        assert ctx.get_buff_instance(target, "코스트감소_테스트") is not None
        # 이번 라운드에는 아직 반영되지 않는다.
        max_cost = ctx.characters[target].status[CombatStatType.COST_PER_TURN]
        assert ctx.characters[target].status.remaining_cost == max_cost

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)

        assert ctx.characters[target].status.remaining_cost == max_cost - 1

        # duration_turn_value=2이므로 다음 라운드가 끝나면 제거된다.
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        assert ctx.get_buff_instance(target, "코스트감소_테스트") is None
