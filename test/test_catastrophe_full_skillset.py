"""패시브 스킬(PassiveSkill) + 코스트 2 스킬(Cost2Skill) + 코스트 3 스킬(Cost3Skill)을
가진 캐릭터의 스킬셋이 실제 스프레드시트 행 그대로(각 데이터클래스의 from_dict()를
거쳐) 로드했을 때 의도대로 동작하는지 확인하는 통합 테스트.

캐릭터/스킬 id는 실제 스프레드시트의 고유명사를 코드에 노출하지 않도록 모두
일반화한 이름(Catastrophe, PassiveSkill, PassiveBuff, Cost2Skill, Cost3Skill)을
쓴다.

여기 쓰인 딕셔너리는 실제 '버프'/'버프_패시브'/'스킬_캐릭터'/'스킬_패시브' 시트에서
그대로 읽어온 값이다(헤더 rename 이후의 buff_id_1/2 포함).
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
    """'버프' 시트의 재앙/도발 행."""
    return {
        "재앙": BuffData.from_dict(
            {
                "id": "재앙",
                "buff_name": "BuffCatastrophe",
                "duration_turn_value": "",
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": "패시브로 축적되는 저주. 해제할 수 없다. "
                "전투 종료 시 남은 스택×3만큼 자신의 체력이 감소한다.",
                "is_debuff": False,
                "max_stack": 10,
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
                "description": "적의 공격과 부가 효과를 자신에게 유도 (도발 공격)",
                "is_debuff": False,
            }
        ),
    }


def _passive_buff_dict() -> dict[str, PassiveBuffData]:
    """'버프_패시브' 시트의 행 하나(받는 대미지 감소 모디파이어)."""
    return {
        "PassiveBuff": PassiveBuffData.from_dict(
            {
                "id": "PassiveBuff",
                "buff_name": "BuffReceivedDamage",
                "value": -5,
                "value_type": "퍼센트",
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
                "value_0": 150,
                "value_type_0": "퍼센트",
                "buff_id_0": "",
                "buff_stack_cap_0": "",
                "target_override_0": "",
                "effect_1": "SkillEffectConsumeStackForDamage",
                "condition_1": "",
                "condition_value_1": "",
                "value_source_1": "해당 행동으로 소모한 버프 스택 수",
                "value_1": 300,
                "value_type_1": "퍼센트",
                "buff_id_1": "재앙",
                "buff_stack_cap_1": 5,
                "target_override_1": "",
                "effect_2": "SkillEffectAddBuff",
                "condition_2": "ConsumedBuffStackCountCondition",
                "condition_value_2": 3,
                "value_source_2": "",
                "value_2": "",
                "value_type_2": "",
                "buff_id_2": "도발",
                "buff_stack_cap_2": "",
                "target_override_2": "",
                "description": (
                    "대상에게 공격 굴림 100%만큼 대미지를 입힌다. [재앙]을 최대 "
                    "5스택까지 자동으로 소모하고, 소모한 스택 수×3만큼 최종 "
                    "대미지가 증가한다. 3스택 이상 소모했다면 대상에게 1턴간 "
                    "[도발]을 부여한다."
                ),
            }
        ),
        "Cost3Skill": SkillData.from_dict(
            {
                "id": "Cost3Skill",
                "target_rule": "SkillTargetRuleNamed",
                "target_count": 1,
                "cost": 3,
                "effect_0": "SkillEffectHealAndFillBuffStack",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "해당 행동으로 증가한 버프 스택 수",
                "value_0": 500,
                "value_type_0": "퍼센트",
                "buff_id_0": "재앙",
                "buff_stack_cap_0": 10,
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
                    "대상의 체력을 (앞으로 더 쌓을 수 있는 [재앙]의 수)×5만큼 "
                    "회복시키고 즉시 자신의 [재앙] 스택을 최대치만큼 쌓는다. "
                    "전체 회복량이 대상에게 필요한 회복량을 초과하면 남는 양만큼 "
                    "자신의 체력을 회복한다."
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
                "trigger": "적 후행 시",
                "target_type": "자신을 포함한 같은 열 아군",
                "buff_id": "PassiveBuff",
                "effect_0": "SkillEffectAddBuff",
                "value_source_0": "",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "재앙",
                "target_override_0": "자신",
                "condition_0": "AllyInSameColumnWasAttackedCondition",
                "condition_value_0": "",
                "effect_1": "SkillEffectAddBuff",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "재앙",
                "target_override_1": "자신",
                "condition_1": "HolderWasAttackedCondition",
                "condition_value_1": "",
                "description": (
                    "라운드의 최종 위치를 기준으로 자신을 포함한 같은 열의 "
                    "아군이 받는 대미지 -5%\n같은 열의 아군이 피격 시 [재앙] "
                    "1스택 누적, 만약 피격당한 것이 자신이라면 1스택 추가 누적."
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
    """패시브 스킬: 같은 열(자신 포함) 피격 시 [재앙] 누적."""

    def test_stack_gained_when_same_column_ally_is_hit(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset(
                "Catastrophe",
                passive_skill_id="PassiveSkill",
                skill_1_id="Cost2Skill",
                skill_2_id="Cost3Skill",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("동료"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/동료]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        # 동료(같은 열)가 맞았으므로 1스택. 자신은 맞지 않았으므로 추가 스택은 없다.
        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 1

    def test_extra_stack_gained_when_holder_itself_is_hit(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/Catastrophe]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        # 같은 열 피격(효과 0) + 자신 피격(효과 1) 둘 다 조건을 만족해 2스택.
        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 2

    def test_received_damage_reduction_applies_to_holder(self):
        """받는 대미지 -5% 모디파이어가 실제 공격에도 적용되는지 확인한다.
        ATK_ROLL을 결정론적으로 만들기 위해 milestone_n=0(주사위 없음),
        공격자 atk=100으로 고정한다(대미지 = 100, -5% 적용 시 95)."""

        def _run(passive_skill_id):
            ctx = _make_context(milestone_n=0)
            manager = _setup_enemy_pre_phase(ctx)
            catastrophe_id = CharacterId("Catastrophe")
            ctx.add_character(
                get_test_preset(
                    "Catastrophe", max_hp=300, passive_skill_id=passive_skill_id
                ),
                FactionType.ALLY,
                BattlefieldColumnIndex(0),
            )
            ctx.add_character(
                get_test_preset("적군", atk=100),
                FactionType.ENEMY,
                BattlefieldColumnIndex(0),
            )
            manager.process_command(
                parse_character_command(CharacterId("적군"), "[공격/Catastrophe]", ctx)
            )
            manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
            return ctx.characters[catastrophe_id].status.curr_hp

        baseline_hp_after = _run(passive_skill_id=None)
        passive_hp_after = _run(passive_skill_id="PassiveSkill")

        assert baseline_hp_after == 300 - 100
        assert passive_hp_after == 300 - 95
        assert passive_hp_after > baseline_hp_after


class TestCost2Skill:
    """코스트 2 스킬: 자신에게 쌓인 [재앙] 스택 소모 clamp + 소모량 기반
    대미지 가산 + 조건부 도발 부여. STAT_ATK_ROLL(공격 굴림값)의 무작위성을
    없애기 위해 milestone_n=0, 공격자 atk=0으로 설정해 effect_0(기본 대미지)을
    0으로 고정한다.

    [재앙]은 패시브 스킬을 통해 항상 시전자 자신에게 쌓이므로, 이 스킬도
    대상이 아니라 시전자 자신의 스택을 소모한다."""

    def _make_ready_context(self):
        ctx = _make_context(milestone_n=0)
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Catastrophe")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Catastrophe", atk=0, skill_1_id="Cost2Skill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=200),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        return ctx, manager, caster, target

    def test_consumes_up_to_cap_and_grants_taunt_when_threshold_met(self):
        ctx, manager, caster, target = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=caster, buff_id="재앙", stack_value=4
            )
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost2Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        # 기본 대미지 0(atk=0) + 소모 4스택×300% = 12.
        assert hp_before - hp_after == 12
        assert ctx.get_buff_stack(caster, "재앙") == 0
        assert any(
            b.id == "도발" for b in ctx.buff_container.get_buffs_by(target, None)
        )

    def test_taunt_not_granted_below_threshold(self):
        ctx, manager, caster, target = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=caster, buff_id="재앙", stack_value=2
            )
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(
            parse_character_command(caster, "[Cost2Skill/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 6
        assert not any(
            b.id == "도발" for b in ctx.buff_container.get_buffs_by(target, None)
        )

    def test_taunt_log_entry_not_emitted_below_threshold(self):
        """게이트에 막혀 실제로는 부여되지 않은 버프를 "[버프] 부여" 로그로
        남기면 안 된다 — 답글이 실제 게임 상태와 어긋나게 된다."""
        ctx, manager, caster, target = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=caster, buff_id="재앙", stack_value=2
            )
        )

        before = len(ctx.results)
        manager.process_command(
            parse_character_command(caster, "[Cost2Skill/적군]", ctx)
        )
        new_entries = [e for r in ctx.results[before:] for e in r.log_entries]

        assert not any("도발" in e.result for e in new_entries)

    def test_requested_consumption_clamps_to_available_stack(self):
        """cap 5보다 적게 보유(3스택)해도 실패 없이 있는 만큼만 소모된다."""
        ctx, manager, caster, target = self._make_ready_context()
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=caster, buff_id="재앙", stack_value=3
            )
        )

        manager.process_command(
            parse_character_command(caster, "[Cost2Skill/적군]", ctx)
        )

        assert ctx.get_buff_stack(caster, "재앙") == 0


class TestCost3Skill:
    """코스트 3 스킬: 남은 스택만큼 대상을 회복시키고 자신의 [재앙]을
    최대치까지 채운다. 초과 회복분은 자신에게 돌아간다."""

    def test_heals_target_fills_own_stack_and_overflow_heals_self(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Catastrophe")
        ally = CharacterId("아군")
        ctx.add_character(
            get_test_preset(
                "Catastrophe", skill_1_id="Cost3Skill", initial_hp=90, max_hp=100
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군", initial_hp=84, max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=caster, buff_id="재앙", stack_value=6
            )
        )

        # 남은 여유 = 10-6=4 -> 회복량 = 4*5=20. 아군은 84->100(16 흡수),
        # 초과 4는 시전자 자신에게: 90+4=94. 자신의 재앙 스택은 최대치(10)로 충전.
        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/아군]", ctx)
        )

        assert ctx.characters[ally].status.curr_hp == 100
        assert ctx.characters[caster].status.curr_hp == 94
        assert ctx.get_buff_stack(caster, "재앙") == 10
