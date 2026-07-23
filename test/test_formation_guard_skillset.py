"""패시브 스킬(PassiveSkill) + 코스트 2 스킬(Cost2Skill) + 코스트 3 스킬(Cost3Skill)을
가진 캐릭터의 스킬셋이 실제 스프레드시트 행 그대로(각 데이터클래스의 from_dict()를
거쳐) 로드했을 때 의도대로 동작하는지 확인하는 통합 테스트.

캐릭터/스킬/버프 id는 실제 스프레드시트의 고유명사를 코드에 노출하지 않도록 모두
일반화한 이름(Formation, PassiveSkill, Cost2Skill, Cost3Skill, Weaken)을 쓴다.
[도발]/[방어막]/[반사]는 여러 캐릭터가 공유하는 범용 게임 시스템 명칭(재앙/균열과
동급)이라 그대로 사용한다.

여기 쓰인 딕셔너리는 실제 '버프'/'스킬_캐릭터'/'스킬_패시브' 시트에서 그대로
읽어온 값이다.

[코스트 2 스킬]의 "자신에게 [Formation]이 부여된 상태라면 추가로 [Weaken]을
부여한다"는 대상(적)에게 부여하는 것으로 해석해 구현했다 — 도발과 함께 걸리는
추가 견제 효과로 보는 편이 [Formation]이 갖는 "밀집 대형 보상" 컨셉과 맞다고
판단했다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


def _buff_dict() -> dict[str, BuffData]:
    """'버프' 시트의 행들."""
    return {
        "Formation": BuffData.from_dict(
            {
                "id": "Formation",
                "buff_name": "BuffFormation",
                "duration_turn_value": 1,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": -5,
                "value_type": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": "버프. 받는 대미지가 5% 감소한다.",
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "Weaken": BuffData.from_dict(
            {
                "id": "Weaken",
                "buff_name": "BuffGivenDamage",
                "duration_turn_value": 1,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": -15,
                "value_type": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": "디버프. 주는 대미지가 15% 감소한다.",
                "is_debuff": True,
                "max_stack": "",
            }
        ),
        "도발": BuffData.from_dict(
            {
                "id": "도발",
                "buff_name": "BuffTaunt",
                "duration_turn_value": 1,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": "디버프. 대상이 가하는 모든 공격과 그 부가 효과가 부여자를 향한다.",
                "is_debuff": True,
                "max_stack": "",
            }
        ),
        "방어막": BuffData.from_dict(
            {
                "id": "방어막",
                "buff_name": "BuffNoDamage",
                "duration_turn_value": 2,
                "duration_count_value": 1,
                "duration_count_deduct_condition": "피격 시",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": "버프. 받는 대미지를 무효화한다. 부가 효과는 그대로 적용된다.",
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "반사": BuffData.from_dict(
            {
                "id": "반사",
                "buff_name": "BuffReflect",
                "duration_turn_value": 2,
                "duration_count_value": 1,
                "duration_count_deduct_condition": "피격 시",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": (
                    "버프. 받는 대미지를 무효화하고, 무효화한 대미지의 40%를 "
                    "공격자에게 되돌려 보낸다. 부가 효과는 그대로 적용된다."
                ),
                "is_debuff": False,
                "max_stack": "",
            }
        ),
    }


def _skill_dict() -> dict[str, SkillData]:
    """'스킬_캐릭터' 시트의 코스트 2/코스트 3 스킬 행."""
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
                "value_0": 180,
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
                "buff_id_1": "도발",
                "buff_stack_cap_1": "",
                "target_override_1": "",
                "effect_2": "SkillEffectAddBuffIfHolderHasFormationBuff",
                "condition_2": "",
                "condition_value_2": "",
                "value_source_2": "",
                "value_2": "",
                "value_type_2": "",
                "buff_id_2": "Weaken",
                "buff_stack_cap_2": "",
                "target_override_2": "",
                "description": (
                    "대상에게 공격 굴림 180%만큼 대미지를 입히고 1턴간 [도발]을 "
                    "부여한다. 만약 자신에게 [Formation]이 부여된 상태라면 추가로 "
                    "1턴간 [Weaken]을 부여한다."
                ),
            }
        ),
        "Cost3Skill": SkillData.from_dict(
            {
                "id": "Cost3Skill",
                "target_rule": "SkillTargetRuleAllyColumn",
                "target_count": 1,
                "cost": 3,
                "effect_0": "SkillEffectShieldOrReflectIfTargetHasFormationBuff",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "방어막",
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
                "description": (
                    "사거리 내에서 열 1개를 지정한다. 범위 내의 모든 아군에게 "
                    "2턴/1회 동안 [방어막]을 부여한다. 만약 그 아군에게 "
                    "[Formation]이 부여되어 있다면 [방어막] 대신 [반사]를 부여한다."
                ),
            }
        ),
    }


def _passive_skill_dict() -> dict[str, PassiveSkillData]:
    """'스킬_패시브' 시트의 패시브 스킬 행."""
    return {
        "PassiveSkill": PassiveSkillData.from_dict(
            {
                "id": "PassiveSkill",
                "trigger": "라운드 시작",
                "target_type": "전체 아군",
                "buff_id": "",
                "effect_0": "SkillEffectAddBuff",
                "value_source_0": "",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "Formation",
                "target_override_0": "",
                "condition_0": "AllyInRangeCountCondition",
                "condition_value_0": 3,
                "effect_1": "",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "",
                "target_override_1": "",
                "condition_1": "",
                "condition_value_1": "",
                "description": (
                    "라운드 시작 시 사거리 내에 자신을 제외한 아군이 3명 이상이라면 "
                    "아군 전체에게 1턴간 [Formation]을 부여한다."
                ),
            },
            {},
        ),
    }


def _make_context(*, milestone_n: int = 0) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict=_buff_dict(),
        skill_dict=_skill_dict(),
        passive_skill_dict=_passive_skill_dict(),
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


class TestPassiveSkill:
    """패시브 스킬: 라운드 시작 시 사거리 내 자신 제외 아군이 3명 이상이면
    아군 전체에게 1턴간 [Formation]을 부여한다."""

    def _has_formation(self, context: BattlefieldContext, char_id: CharacterId) -> bool:
        return context.buff_container.get_buff(char_id, "Formation") is not None

    def test_grants_formation_to_all_allies_when_three_or_more_in_range(self):
        ctx = _make_context()
        manager = RoundManager(ctx)
        caster = CharacterId("Formation")
        ally1 = CharacterId("Ally1")
        ally2 = CharacterId("Ally2")
        ally3 = CharacterId("Ally3")
        ctx.add_character(
            get_test_preset(
                "Formation", attack_range=10, passive_skill_id="PassiveSkill"
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(get_test_preset("Ally1"), FactionType.ALLY, BattlefieldColumnIndex(1))
        ctx.add_character(get_test_preset("Ally2"), FactionType.ALLY, BattlefieldColumnIndex(2))
        ctx.add_character(get_test_preset("Ally3"), FactionType.ALLY, BattlefieldColumnIndex(3))

        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)

        assert self._has_formation(ctx, caster)
        assert self._has_formation(ctx, ally1)
        assert self._has_formation(ctx, ally2)
        assert self._has_formation(ctx, ally3)

    def test_no_formation_when_fewer_than_three_allies_in_range(self):
        ctx = _make_context()
        manager = RoundManager(ctx)
        caster = CharacterId("Formation")
        ally1 = CharacterId("Ally1")
        ally2 = CharacterId("Ally2")
        ctx.add_character(
            get_test_preset(
                "Formation", attack_range=10, passive_skill_id="PassiveSkill"
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(get_test_preset("Ally1"), FactionType.ALLY, BattlefieldColumnIndex(1))
        ctx.add_character(get_test_preset("Ally2"), FactionType.ALLY, BattlefieldColumnIndex(2))

        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)

        assert not self._has_formation(ctx, caster)
        assert not self._has_formation(ctx, ally1)
        assert not self._has_formation(ctx, ally2)


class TestCost2Skill:
    """코스트 2 스킬: 공격 굴림 180% 대미지 + 대상에게 1턴간 [도발] 부여.
    시전자가 [Formation]을 보유한 상태라면 대상에게 추가로 1턴간 [Weaken]도
    부여한다. STAT_ATK_ROLL의 무작위성을 없애기 위해 milestone_n=0, 공격자
    atk=100으로 고정한다(180% 대미지 = 180)."""

    def _make_ready_context(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Formation")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Formation", atk=100, skill_1_id="Cost2Skill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        return ctx, manager, caster, target

    def test_deals_damage_and_taunts_without_formation(self):
        ctx, manager, caster, target = self._make_ready_context()

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost2Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 180
        assert ctx.buff_container.get_buff(target, "도발") is not None
        assert ctx.buff_container.get_buff(target, "Weaken") is None

    def test_also_grants_weaken_to_target_when_caster_has_formation(self):
        ctx, manager, caster, target = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(given_by=caster, applied_to=caster, buff_id="Formation")
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost2Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 180
        assert ctx.buff_container.get_buff(target, "도발") is not None
        assert ctx.buff_container.get_buff(target, "Weaken") is not None


class TestCost3Skill:
    """코스트 3 스킬: 지정한 열의 아군 전체에게 2턴/1회 동안 [방어막]을 부여한다.
    이미 [Formation]을 보유한 아군에게는 [방어막] 대신 [반사]를 부여한다."""

    def test_grants_shield_or_reflect_per_target_formation_state(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Formation")
        with_formation = CharacterId("WithFormation")
        without_formation = CharacterId("WithoutFormation")
        ctx.add_character(
            get_test_preset("Formation", skill_1_id="Cost3Skill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("WithFormation"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("WithoutFormation"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=with_formation, applied_to=with_formation, buff_id="Formation"
            )
        )

        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/1열]", ctx)
        )

        assert ctx.buff_container.get_buff(with_formation, "반사") is not None
        assert ctx.buff_container.get_buff(with_formation, "방어막") is None
        assert ctx.buff_container.get_buff(without_formation, "방어막") is not None
        assert ctx.buff_container.get_buff(without_formation, "반사") is None
        assert ctx.buff_container.get_buff(caster, "방어막") is not None


class TestReflectBuff:
    """[반사] 버프: 받는 대미지를 무효화하고, 무효화한 대미지의 40%를 공격자에게
    고정값으로 되돌려 보낸다. STAT_ATK_ROLL의 무작위성을 없애기 위해
    milestone_n=0, 공격자 atk=100으로 고정한다."""

    def test_nullifies_damage_and_reflects_forty_percent(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        attacker = CharacterId("Formation")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Formation", atk=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            BuffAddData(given_by=target, applied_to=target, buff_id="반사")
        )

        attacker_hp_before = ctx.characters[attacker].status.curr_hp
        target_hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(attacker, "[공격/적군]", ctx)
        )
        attacker_hp_after = ctx.characters[attacker].status.curr_hp
        target_hp_after = ctx.characters[target].status.curr_hp

        assert target_hp_before == target_hp_after
        assert attacker_hp_before - attacker_hp_after == 40
        assert ctx.buff_container.get_buff(target, "반사") is None
