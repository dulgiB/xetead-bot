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
from battle.objects.buff.models import BuffData
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.models import SkillData
from helpers import get_test_preset


def _buff_dict() -> dict[str, BuffData]:
    """'버프' 시트의 재앙/도발/PassiveBuff 행."""
    return {
        "재앙": BuffData.from_dict(
            {
                "id": "재앙",
                "buff_name": "BuffCatastrophe",
                "duration_turn_value": "",
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": 5,
                "value_type_0": "정수",
                "condition": "",
                "condition_value": "",
                "description": "패시브로 축적되는 저주. 해제할 수 없다. "
                "전투 종료 시 남은 스택×5만큼 자신의 체력이 감소한다.",
                "is_debuff": False,
                "max_stack": 10,
            }
        ),
        # 패시브가 매 라운드 좌우 1열 아군에게 새로 부여하는 경감 버프.
        # 부여 시점이 적의 대미지 정산 직전(ON_ENEMY_POST_ACTION)이라
        # 그 라운드의 피격부터 곧바로 적용된다.
        "PassiveBuff": BuffData.from_dict(
            {
                "id": "PassiveBuff",
                "buff_name": "BuffReceivedDamage",
                "duration_turn_value": 1,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": -5,
                "value_type_0": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": "받는 대미지 -5%",
                "is_debuff": False,
            }
        ),
        "도발": BuffData.from_dict(
            {
                "id": "도발",
                "buff_name": "BuffTaunt",
                "duration_turn_value": 1,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": "",
                "value_type_0": "",
                "condition": "",
                "condition_value": "",
                "description": "적의 공격과 부가 효과를 자신에게 유도 (도발 공격)",
                "is_debuff": False,
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
                "value_1": 500,
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
                    "5스택까지 자동으로 소모하고, 소모한 스택 수×5만큼 최종 "
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
                "value_0": 300,
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
                    "대상의 체력을 (앞으로 더 쌓을 수 있는 [재앙]의 수)×3만큼 "
                    "회복시키고 즉시 자신의 [재앙] 스택을 최대치만큼 쌓는다. "
                    "전체 회복량이 대상에게 필요한 회복량을 초과하면 남는 양만큼 "
                    "자신의 체력을 회복한다."
                ),
            }
        ),
    }


def _passive_skill_dict() -> dict[str, PassiveSkillData]:
    """'스킬_패시브' 시트의 패시브 스킬 행.

    effect_0/1(스택 누적)은 damaged_this_round에 의존해 적 후행이 확정된 뒤에,
    effect_2(경감 버프 부여)는 그 라운드의 피격을 실제로 경감해야 하므로 확정
    전에 평가된다 — PassiveSkillWrapperBuff가 역할을 나눠 각각 등록한다.
    """
    return {
        "PassiveSkill": PassiveSkillData.from_dict(
            {
                "id": "PassiveSkill",
                "trigger": "적 후행 시",
                "target_type": "자신을 포함한 좌우 1열 아군",
                "buff_id": "",
                # value_0은 수치가 아니라 "좌우 몇 열까지 볼지"(반경)다.
                "effect_0": "SkillEffectAddBuffPerDamagedColumn",
                "value_source_0": "",
                "value_0": 1,
                "value_type_0": "",
                "buff_id_0": "재앙",
                "target_override_0": "자신",
                "condition_0": "",
                "condition_value_0": "",
                "effect_1": "SkillEffectAddBuff",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "재앙",
                "target_override_1": "자신",
                "condition_1": "HolderWasAttackedCondition",
                "condition_value_1": "",
                "effect_2": "SkillEffectAddBuff",
                "value_source_2": "",
                "value_2": "",
                "value_type_2": "",
                "buff_id_2": "PassiveBuff",
                "target_override_2": "",
                "condition_2": "",
                "condition_value_2": "",
                "description": (
                    "라운드의 최종 위치를 기준으로 자신을 포함한 같은 열 및 "
                    "좌우 1열의 아군이 받는 대미지 -5%\n해당 범위의 열에서 "
                    "누군가 피격되면 1열당 [재앙] 1스택 누적, 만약 피격당한 "
                    "것이 자신이라면 1스택 추가 누적."
                ),
            },
            {},
        ),
    }


def _make_context(*, milestone_n: int = 1) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict=_buff_dict(),
        skill_dict=_skill_dict(),
        passive_skill_dict=_passive_skill_dict(),
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
    """패시브 스킬: 자신을 포함한 좌우 1열 범위에서 피격이 일어난 열 수만큼
    [재앙]을 누적하고(자신이 맞았다면 1스택 추가), 같은 범위의 아군에게
    받는 대미지 경감 버프를 부여한다."""

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

    def test_one_stack_per_damaged_adjacent_column(self):
        """좌우 1열에서 피격이 일어나면 열 하나당 1스택. 자신이 맞지 않았으므로
        추가 스택은 없다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.add_character(
            get_test_preset("아군_좌"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("아군_우"), FactionType.ALLY, BattlefieldColumnIndex(2)
        )
        ctx.add_character(
            get_test_preset("적군_1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군_2"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군_1"), "[공격/아군_좌]", ctx)
        )
        manager.process_command(
            parse_character_command(CharacterId("적군_2"), "[공격/아군_우]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 2

    def test_stacks_cap_at_four_per_round(self):
        """3개 열 전부 피격 + 자신도 피격 = 라운드당 최대치인 4스택."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.add_character(
            get_test_preset("아군_좌"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("아군_우"), FactionType.ALLY, BattlefieldColumnIndex(2)
        )
        for i, column in enumerate((0, 1, 2)):
            ctx.add_character(
                get_test_preset(f"적군_{i}"),
                FactionType.ENEMY,
                BattlefieldColumnIndex(column),
            )

        for name, target in (
            ("적군_0", "아군_좌"),
            ("적군_1", "Catastrophe"),
            ("적군_2", "아군_우"),
        ):
            manager.process_command(
                parse_character_command(CharacterId(name), f"[공격/{target}]", ctx)
            )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 4

    def test_multiple_allies_hit_in_one_column_count_once(self):
        """같은 열에서 두 명이 맞아도 그 열 몫은 1스택이다 — "피격당한 아군 수"가
        아니라 "피격당한 열 수"로 세기 때문."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.add_character(
            get_test_preset("아군_1"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("아군_2"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군_1"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군_2"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군_1"), "[공격/아군_1]", ctx)
        )
        manager.process_command(
            parse_character_command(CharacterId("적군_2"), "[공격/아군_2]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 1

    def test_column_beyond_adjacent_range_is_ignored(self):
        """2열 이상 떨어진 아군의 피격은 스택을 주지 않는다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", passive_skill_id="PassiveSkill"),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("먼 아군"), FactionType.ALLY, BattlefieldColumnIndex(2)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )

        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/먼 아군]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert ctx.get_buff_stack(catastrophe_id, "재앙") == 0

    def test_received_damage_reduction_applies_to_adjacent_column_ally(self):
        """경감 버프가 인접 열 아군에게도 그 라운드의 피격부터 적용된다.
        (버프 모디파이어 경로였을 때는 홀더 본인에게만 적용됐다.)
        ATK_ROLL을 결정론적으로 만들기 위해 milestone_n=0, 공격자 atk=100으로
        고정한다(대미지 = 100, -5% 적용 시 95)."""

        def _run(passive_skill_id):
            ctx = _make_context(milestone_n=0)
            manager = _setup_enemy_pre_phase(ctx)
            ally_id = CharacterId("아군")
            ctx.add_character(
                get_test_preset("Catastrophe", passive_skill_id=passive_skill_id),
                FactionType.ALLY,
                BattlefieldColumnIndex(0),
            )
            ctx.add_character(
                get_test_preset("아군", max_hp=300),
                FactionType.ALLY,
                BattlefieldColumnIndex(1),
            )
            ctx.add_character(
                get_test_preset("적군", atk=100),
                FactionType.ENEMY,
                BattlefieldColumnIndex(1),
            )
            manager.process_command(
                parse_character_command(CharacterId("적군"), "[공격/아군]", ctx)
            )
            manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
            return ctx.characters[ally_id].status.curr_hp

        assert _run(passive_skill_id=None) == 300 - 100
        assert _run(passive_skill_id="PassiveSkill") == 300 - 95

    def test_battle_end_damage_uses_sheet_value_per_stack(self):
        """전투 종료 시 남은 스택 × ("버프" 시트 value_0)만큼 체력이 깎인다."""
        ctx = _make_context()
        _setup_ally_phase(ctx)
        catastrophe_id = CharacterId("Catastrophe")
        ctx.add_character(
            get_test_preset("Catastrophe", max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=catastrophe_id,
                applied_to=catastrophe_id,
                buff_id="재앙",
                stack_value=3,
            )
        )

        ctx.on_battle_end()

        assert ctx.characters[catastrophe_id].status.curr_hp == 100 - 15

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

        # 기본 대미지 0(atk=0) + 소모 4스택×500% = 20.
        assert hp_before - hp_after == 20
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

        assert hp_before - hp_after == 10
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
            get_test_preset("아군", initial_hp=94, max_hp=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster, applied_to=caster, buff_id="재앙", stack_value=6
            )
        )

        # 남은 여유 = 10-6=4 -> 회복량 = 4*3=12. 아군은 94->100(6 흡수),
        # 초과 6은 시전자 자신에게: 90+6=96. 자신의 재앙 스택은 최대치(10)로 충전.
        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/아군]", ctx)
        )

        assert ctx.characters[ally].status.curr_hp == 100
        assert ctx.characters[caster].status.curr_hp == 96
        assert ctx.get_buff_stack(caster, "재앙") == 10
