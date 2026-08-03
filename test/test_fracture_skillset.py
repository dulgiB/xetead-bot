"""패시브 스킬(PassiveSkill) + 코스트 2 스킬(Cost2Skill) + 코스트 3 스킬(Cost3Skill)을
가진 캐릭터의 스킬셋이 실제 스프레드시트 행 그대로(각 데이터클래스의 from_dict()를
거쳐) 로드했을 때 의도대로 동작하는지 확인하는 통합 테스트.

캐릭터/스킬 id는 실제 스프레드시트의 고유명사를 코드에 노출하지 않도록 모두
일반화한 이름(Fracture, PassiveSkill, PassiveBuff, Cost2Skill, Cost3Skill)을
쓴다. [균열]은 여러 캐릭터가 공유하는 범용 게임 시스템 명칭(재앙/도발과 동급)이라
그대로 사용한다.

여기 쓰인 딕셔너리는 실제 '버프'/'버프_패시브'/'스킬_캐릭터'/'스킬_패시브' 시트에서
그대로 읽어온 값이다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData, PassiveBuffData
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


def _buff_dict() -> dict[str, BuffData]:
    """'버프' 시트의 [균열] 행 + 패시브의 "일반 디버프" 분기를 [균열]과 구분해서
    검증하기 위한 무관한 디버프 하나."""
    return {
        "균열": BuffData.from_dict(
            {
                "id": "균열",
                "buff_name": "BuffFracture",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": "디버프. 최대 5회까지 중첩된다. 단독으로는 쓸모가 없다.",
                "is_debuff": True,
                "max_stack": 5,
            }
        ),
        "다른디버프": BuffData.from_dict(
            {
                "id": "다른디버프",
                # BuffFracture는 순수 마커라 수치 부작용이 없다 — [균열]과 구분되는
                # "그냥 디버프가 있다"는 상태만 재현하기 위해 재사용한다.
                "buff_name": "BuffFracture",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": "테스트용 무관 디버프(수치 효과 없음)",
                "is_debuff": True,
                "max_stack": "",
            }
        ),
    }


def _passive_buff_dict() -> dict[str, PassiveBuffData]:
    """'버프_패시브' 시트의 행 하나(디버프 대상 공격 시 주는 대미지 증가 모디파이어)."""
    return {
        "PassiveBuff": PassiveBuffData.from_dict(
            {
                "id": "PassiveBuff",
                "buff_name": "BuffGivenDamageAgainstDebuff",
                "value": 20,
                "value_type": "퍼센트",
                "condition": "TargetHasDebuffCondition",
                "condition_value": "",
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
                "value_0": 230,
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
                "buff_id_1": "균열",
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
                    "대상에게 공격 굴림 230%만큼 대미지를 입히고 2턴간 [균열]을 부여한다."
                ),
            }
        ),
        "Cost3Skill": SkillData.from_dict(
            {
                "id": "Cost3Skill",
                "target_rule": "SkillTargetRuleNamed",
                "target_count": 1,
                "cost": 3,
                "effect_0": "SkillEffectDamageByDebuffStackTier",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "공격 굴림값",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "균열",
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
                    "[균열] 중첩 수에 따라 효과가 달라진다. 1~2스택: 공격 굴림 "
                    "280%만큼 대미지를 입히고 [균열]을 1스택 추가한다(지속시간 2턴 "
                    "갱신). 3~4스택: 공격 굴림 350%만큼 대미지를 입히고 [균열]을 "
                    "1스택 추가한다(지속시간 2턴 갱신). 5스택: 공격 굴림 500%만큼 "
                    "대미지를 입히고 모든 스택을 삭제한다."
                ),
            }
        ),
    }


def _passive_skill_dict(
    passive_buff_dict: dict[str, PassiveBuffData],
) -> dict[str, PassiveSkillData]:
    """'스킬_패시브' 시트의 패시브 스킬 행."""
    return {
        "PassiveSkill": PassiveSkillData.from_dict(
            {
                "id": "PassiveSkill",
                "trigger": "행동 시",
                "target_type": "자신",
                "buff_id": "PassiveBuff",
                "effect_0": "",
                "value_source_0": "",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "",
                "target_override_0": "",
                "condition_0": "",
                "condition_value_0": "",
                "effect_1": "",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "",
                "target_override_1": "",
                "condition_1": "",
                "condition_value_1": "",
                "description": (
                    "디버프가 걸린 적을 공격하면 주는 대미지가 20% 증가한다. "
                    "대상에게 [균열]이 있다면 추가로 5% 증가한다."
                ),
            },
            passive_buff_dict,
        ),
    }


def _make_context(*, milestone_n: int = 1) -> BattlefieldContext:
    passive_buff_dict = _passive_buff_dict()
    return BattlefieldContext(
        buff_dict=_buff_dict(),
        skill_dict=_skill_dict(),
        passive_skill_dict=_passive_skill_dict(passive_buff_dict),
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
    """패시브 스킬: 디버프 걸린 대상 공격 시 대미지 +20%, [균열] 보유 시 추가 +5%.

    STAT_ATK_ROLL의 무작위성을 없애기 위해 milestone_n=0, 공격자 atk=100으로
    고정한다(기본 대미지 = 100).
    """

    def _run(self, *, target_debuff_id: str | None) -> int:
        ctx = _make_context(milestone_n=0)
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Fracture")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset(
                "Fracture",
                atk=100,
                passive_skill_id="PassiveSkill",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        if target_debuff_id is not None:
            ctx.buff_container.add(
                BuffAddData(
                    given_by=caster, applied_to=target, buff_id=target_debuff_id
                )
            )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(parse_character_command(caster, "[공격/적군]", ctx))
        hp_after = ctx.characters[target].status.curr_hp
        return hp_before - hp_after

    def test_no_bonus_without_any_debuff(self):
        assert self._run(target_debuff_id=None) == 100

    def test_twenty_percent_bonus_with_unrelated_debuff(self):
        assert self._run(target_debuff_id="다른디버프") == 120

    def test_twenty_five_percent_bonus_with_fracture_debuff(self):
        assert self._run(target_debuff_id="균열") == 125


class TestCost2Skill:
    """코스트 2 스킬: 공격 굴림 230% 대미지 + 대상에게 2턴간 [균열] 1스택 부여.
    STAT_ATK_ROLL의 무작위성을 없애기 위해 milestone_n=0, 공격자 atk=100으로
    고정한다(230% 대미지 = 230)."""

    def test_deals_damage_and_grants_fracture_stack(self):
        ctx = _make_context(milestone_n=0)
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Fracture")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Fracture", atk=100, skill_1_id="Cost2Skill"),
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

        assert hp_before - hp_after == 230
        assert ctx.get_buff_stack(target, "균열") == 1


class TestCost3Skill:
    """코스트 3 스킬: [균열] 스택 수에 따라 대미지 계수와 후속 효과가 3단계로
    분기한다. STAT_ATK_ROLL의 무작위성을 없애기 위해 milestone_n=0, 공격자
    atk=100으로 고정한다."""

    def _make_ready_context(self):
        ctx = _make_context(milestone_n=0)
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Fracture")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Fracture", atk=100, skill_1_id="Cost3Skill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        return ctx, manager, caster, target

    def test_low_tier_deals_280_percent_and_adds_stack(self):
        ctx, manager, caster, target = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=target, buff_id="균열", stack_value=1
            )
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 280
        assert ctx.get_buff_stack(target, "균열") == 2

    def test_mid_tier_deals_350_percent_and_adds_stack(self):
        ctx, manager, caster, target = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=target, buff_id="균열", stack_value=3
            )
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 350
        assert ctx.get_buff_stack(target, "균열") == 4

    def test_max_tier_deals_500_percent_and_clears_all_stacks(self):
        ctx, manager, caster, target = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=target, buff_id="균열", stack_value=5
            )
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 500
        assert ctx.get_buff_stack(target, "균열") == 0
