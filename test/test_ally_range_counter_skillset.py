"""패시브(PassiveSkill) + 코스트 2 스킬(Cost2Skill) + 코스트 3 스킬(Cost3Skill)을 가진
캐릭터의 스킬셋 통합 테스트. 스프레드시트 행이 각 데이터클래스의 from_dict()를
거쳐 로드됐을 때 의도대로 동작하는지 확인한다.

캐릭터/스킬/버프 id는 실제 스프레드시트의 고유명사를 코드에 노출하지 않도록
모두 일반화한 이름(Sentinel, PassiveSkill, Cost2Skill, Cost3Skill, 버프_1,
버프_2, 버프_3)을 쓴다.

시나리오:
- 패시브(PassiveSkill): 자신에게 (패시브가 아닌) 버프가 부여되어 있을 때, 누군가
  사거리 내의 아군을 공격하면 공격자에게 공격 굴림 50%만큼 반격 대미지를
  입힌다. 맞은 아군이 자신이면 80%.
- 코스트 2(Cost2Skill): 대상에게 공격 굴림 230% 대미지 + 자신에게 2턴간
  [버프_1](주는 대미지 +20%) 부여.
- 코스트 3(Cost3Skill): 사거리 내에서 자신 외의 아군을 최대 2명 선택해 2턴간
  [버프_2](주는 대미지 +25%, 받는 대미지 +10%)으로 지정하고, 자신에게
  2턴간 [버프_3](사거리 내 [버프_2] 아군이 공격할 때마다 자신도 그
  대상에게 공격 굴림 60% 대미지)를 부여.
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
from bot.battle_reply_text import format_battle_reply
from helpers import get_test_preset


def _buff_dict() -> dict[str, BuffData]:
    """'버프' 시트의 행들."""
    return {
        "버프_1": BuffData.from_dict(
            {
                "id": "버프_1",
                "buff_name": "BuffGivenDamage",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": 20,
                "value_type_0": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": "버프. 주는 대미지가 20% 증가한다.",
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "버프_2": BuffData.from_dict(
            {
                "id": "버프_2",
                "buff_name": "BuffGivenAndReceivedDamage",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": 25,
                "value_type_0": "퍼센트",
                "value_1": 10,
                "condition": "",
                "condition_value": "",
                "description": (
                    "버프. 주는 대미지가 25% 증가하는 대신 받는 대미지가 10% 증가한다."
                ),
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "버프_3": BuffData.from_dict(
            {
                "id": "버프_3",
                "buff_name": "BuffCounterDamageOnMarkedAllyAttack",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": 60,
                "value_type_0": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": (
                    "버프. 사거리 내의 [버프_2]으로 지정된 아군이 누군가를 "
                    "공격할 때마다 자신도 그 대상에게 공격 굴림 60% 대미지를 입힌다."
                ),
                "is_debuff": False,
                "max_stack": "",
                "reference_buff_id": "버프_2",
            }
        ),
        "받는대미지감소_테스트": BuffData.from_dict(
            {
                "id": "받는대미지감소_테스트",
                "buff_name": "BuffReceivedDamage",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": -50,
                "value_type_0": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": "테스트 전용. 받는 대미지가 50% 감소한다.",
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "반사_테스트": BuffData.from_dict(
            {
                "id": "반사_테스트",
                "buff_name": "BuffReflect",
                "duration_turn_value": 2,
                "duration_count_value": 1,
                "duration_count_deduct_condition": "피격 시",
                "value_0": 40,
                "value_type_0": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": (
                    "테스트 전용. 받는 대미지를 무효화하고, 무효화한 대미지의 "
                    "40%를 공격자에게 되돌려 보낸다."
                ),
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "도발_테스트": BuffData.from_dict(
            {
                "id": "도발_테스트",
                "buff_name": "BuffTaunt",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value_0": "",
                "value_type_0": "",
                "condition": "",
                "condition_value": "",
                "description": "테스트 전용. 도발.",
                "is_debuff": True,
                "max_stack": "",
            }
        ),
    }


def _passive_buff_dict() -> dict[str, PassiveBuffData]:
    """'버프_패시브' 시트의 행(PassiveSkill의 버프 모디파이어 경로)."""
    return {
        "PassiveSkill": PassiveBuffData.from_dict(
            {
                "id": "PassiveSkill",
                "buff_name": "BuffCounterDamageOnAllyInRangeDamaged",
                "value_0": 80,
                "value_type_0": "퍼센트",
                "value_1": 50,
                "condition": "HolderHasBuffCondition",
                "condition_value": "",
                "description": "",
            }
        ),
    }


def _passive_skill_dict() -> dict[str, PassiveSkillData]:
    return {
        "PassiveSkill": PassiveSkillData.from_dict(
            {
                "id": "PassiveSkill",
                "trigger": "사거리 내 아군 피격 시",
                "target_type": "자신",
                "buff_id": "PassiveSkill",
                "description": (
                    "패시브. 자신에게 버프가 부여되어 있을 때 누군가 사거리 내의 "
                    "아군을 공격한다면 공격자에게 공격 굴림 50%만큼 대미지를 입힌다. "
                    "만약 그 아군이 자신이라면 대신 80%."
                ),
            },
            _passive_buff_dict(),
        ),
    }


def _skill_dict() -> dict[str, SkillData]:
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
                "buff_id_1": "버프_1",
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
                    "대상에게 공격 굴림 230%만큼 대미지를 입히고 자신에게 2턴간 "
                    "[버프_1]를 부여한다."
                ),
            }
        ),
        "Cost3Skill": SkillData.from_dict(
            {
                "id": "Cost3Skill",
                "target_rule": "SkillTargetRuleNamed",
                "target_count": 2,
                "cost": 3,
                "effect_0": "SkillEffectAddBuff",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "버프_2",
                "buff_stack_cap_0": "",
                "target_override_0": "",
                "effect_1": "SkillEffectAddBuff",
                "condition_1": "",
                "condition_value_1": "",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "버프_3",
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
                    "사거리 내에서 자신 외의 아군을 대상의 수만큼 선택해 2턴간 "
                    "[버프_2]으로 지정하고, 자신에게 2턴간 [버프_3]를 부여한다."
                ),
            }
        ),
    }


def _make_context() -> BattlefieldContext:
    # milestone_n=0이면 공격 굴림에 주사위가 더해지지 않아(1d6 × 0회) 결과값이
    # 공격력 그대로 나온다 — 테스트를 결정적으로 만들기 위함.
    return BattlefieldContext(
        buff_dict=_buff_dict(),
        skill_dict=_skill_dict(),
        passive_skill_dict=_passive_skill_dict(),
        milestone_n=0,
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


def _buff_add(*, given_by: str, applied_to: str, buff_id: str) -> BuffAddData:
    return BuffAddData(
        given_by=CharacterId(given_by),
        applied_to=CharacterId(applied_to),
        buff_id=buff_id,
    )


class TestPassiveSkill:
    """패시브: 자신에게 버프가 부여되어 있을 때, 사거리 내 아군이 공격받으면
    공격자에게 반격한다. 맞은 아군이 자신이면 반격 비율이 더 높다."""

    def _add_holder_and_ally(self, ctx: BattlefieldContext, *, holder_range: int = 5):
        ctx.add_character(
            get_test_preset(
                "Sentinel",
                atk=50,
                attack_range=holder_range,
                passive_skill_id="PassiveSkill",
            ),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군2", atk=1, max_hp=1000),
            FactionType.ALLY,
            BattlefieldColumnIndex(2),
        )
        ctx.add_character(
            get_test_preset("적군", atk=10, max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(2),
        )

    def test_counters_attacker_when_other_ally_in_range_is_hit(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        enemy = CharacterId("적군")
        # 조건 충족용으로 [버프_1](주는 대미지 수정자)가 아니라 [버프_3](수치를
        # 건드리지 않는 반응형 버프)를 부여한다 — 이 테스트는 반격의 "기본
        # 비율"만 확인하고, 다른 버프와의 중첩은 별도 테스트에서 확인한다.
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_3")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        # 홀더 공격 굴림 50 × 50% = 25.
        assert enemy_hp_before - enemy_hp_after == 25

    def test_counters_at_higher_percent_when_holder_itself_is_hit(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        holder = CharacterId("Sentinel")
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_3")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(
            parse_character_command(enemy, f"[공격/{holder.name}]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        # 홀더 공격 굴림 50 × 80% = 40.
        assert enemy_hp_before - enemy_hp_after == 40

    def test_counter_damage_respects_holders_own_given_damage_buff(self):
        """반격도 홀더가 실제로 가하는 대미지이므로, 홀더가 보유한 [버프_1](주는
        대미지 +20%)가 반격 수치에도 반영되어야 하고 계산식에도 드러나야
        한다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_1")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        before = len(ctx.results)
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp
        reply, calc = format_battle_reply(ctx, enemy, ctx.results[before:])

        # 50 × 50%[PassiveSkill] × (1 + 0.2)[버프_1] = 30.
        assert enemy_hp_before - enemy_hp_after == 30
        assert "0.5[PassiveSkill: Sentinel]" in calc
        assert "0.2[버프_1]" in calc

    def test_counter_damage_respects_attackers_own_received_damage_buff(self):
        """반격 대미지도 공격자(반격 대상)가 평소 자신이 공격당할 때 받는
        "받는 대미지" 버프의 영향을 받아야 한다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_3")
        )
        ctx.buff_container.add(
            _buff_add(
                given_by="적군", applied_to="적군", buff_id="받는대미지감소_테스트"
            )
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        # 50 × 50%[PassiveSkill] × (1 - 0.5)[받는대미지감소_테스트] = 12(내림).
        assert enemy_hp_before - enemy_hp_after == 12

    def test_reply_summary_labels_counter_damage_with_buff_id_and_holder(self):
        """반격 대미지는 명아_테스트(공격받은 아군) 본인이 아니라 Sentinel이
        대신 가한 대미지이므로, 답글 요약에도 "[PassiveSkill: Sentinel]"로
        발생 원인이 드러나야 한다 — 원래 피격 아군 줄에는 라벨이 붙지 않는다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        enemy = CharacterId("적군")
        ally2 = CharacterId("아군2")
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_3")
        )

        before = len(ctx.results)
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        reply, _calc = format_battle_reply(ctx, enemy, ctx.results[before:])

        assert "[PassiveSkill: Sentinel]" in reply
        for line in reply.splitlines():
            if line.startswith(f"▹ {ally2.name} "):
                assert "[" not in line

    def test_no_counter_when_holder_has_no_buff(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        enemy = CharacterId("적군")

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        assert enemy_hp_before == enemy_hp_after

    def test_no_counter_when_ally_damage_is_fully_reflected(self):
        """[반사](BuffReflect)가 아군2의 피해를 완전히 무효화하고 공격자에게
        되돌리는 형태로 대체하면, 그 무효화된 원래 피격 이벤트를 근거로
        코모이디아류(ALLY_IN_RANGE_DAMAGED) 버프가 추가로 발동하면 안 된다 —
        아군2는 실제로는 전혀 대미지를 받지 않았기 때문이다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_3")
        )
        ctx.buff_container.add(
            _buff_add(given_by="아군2", applied_to="아군2", buff_id="반사_테스트")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        # 아군2의 피해가 [반사_테스트]로 전액 무효화되고 공격 굴림 10 ×
        # 40%[반사 계수] = 4만큼만 공격자에게 되돌아간다. 코모이디아
        # (PassiveSkill)의 추가 반격(공격 굴림 50 × 50% = 25)이 더해지면 안 된다.
        assert enemy_hp_before - enemy_hp_after == 4

    def test_no_counter_when_ally_out_of_holders_range(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx, holder_range=1)
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_1")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        assert enemy_hp_before == enemy_hp_after


class TestCost2Skill:
    """코스트 2 스킬: 공격 굴림 230% 대미지 + 자신에게 2턴간 [버프_1] 부여."""

    def test_deals_damage_and_grants_ode_to_self(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Sentinel")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Sentinel", atk=100, skill_1_id="Cost2Skill"),
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
        buff = ctx.buff_container.get_buff(caster, "버프_1")
        assert buff is not None
        assert buff.duration.remaining_turns == 2


class TestCost3Skill:
    """코스트 3 스킬: 사거리 내 자신 외 아군을 대상의 수만큼 선택해 2턴간
    [버프_2] 지정 + 자신에게 2턴간 [버프_3] 부여."""

    def test_grants_nebrospaston_to_chosen_allies_and_galchae_to_self(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Sentinel")
        ally_a = CharacterId("아군A")
        ally_b = CharacterId("아군B")
        ctx.add_character(
            get_test_preset("Sentinel", skill_1_id="Cost3Skill", attack_range=5),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군A"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )
        ctx.add_character(
            get_test_preset("아군B"), FactionType.ALLY, BattlefieldColumnIndex(2)
        )

        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/아군A/아군B]", ctx)
        )

        assert ctx.buff_container.get_buff(ally_a, "버프_2") is not None
        assert ctx.buff_container.get_buff(ally_b, "버프_2") is not None
        galchae = ctx.buff_container.get_buff(caster, "버프_3")
        assert galchae is not None
        assert galchae.duration.remaining_turns == 2

    def test_can_target_fewer_than_the_maximum(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("Sentinel")
        ally_a = CharacterId("아군A")
        ctx.add_character(
            get_test_preset("Sentinel", skill_1_id="Cost3Skill", attack_range=5),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군A"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )

        manager.process_command(
            parse_character_command(caster, "[Cost3Skill/아군A]", ctx)
        )

        assert ctx.buff_container.get_buff(ally_a, "버프_2") is not None
        assert ctx.buff_container.get_buff(caster, "버프_3") is not None


class TestGivenAndReceivedDamageBuff:
    """[버프_2]: 주는 대미지 +25%, 받는 대미지 +10%."""

    def test_increases_given_damage(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        marked = CharacterId("마크아군")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("마크아군", atk=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            _buff_add(given_by="마크아군", applied_to="마크아군", buff_id="버프_2")
        )

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 125

    def test_increases_received_damage(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        marked = CharacterId("마크아군")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset("마크아군", max_hp=1000),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("적군", atk=100),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            _buff_add(given_by="마크아군", applied_to="마크아군", buff_id="버프_2")
        )

        hp_before = ctx.characters[marked].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[공격/마크아군]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        hp_after = ctx.characters[marked].status.curr_hp

        assert hp_before - hp_after == 110


class TestCounterOnMarkedAllyAttackBuff:
    """[버프_3]: 사거리 내의 [버프_2] 아군이 누군가를 공격할 때마다,
    자신도 그 대상에게 공격 굴림 60% 대미지를 입힌다."""

    def _setup(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        holder = CharacterId("Sentinel")
        marked = CharacterId("마크아군")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Sentinel", atk=100, attack_range=5),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("마크아군", atk=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_3")
        )
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="마크아군", buff_id="버프_2")
        )
        return ctx, manager, holder, marked, enemy

    def test_holder_also_deals_damage_to_marked_allys_target(self):
        ctx, manager, holder, marked, enemy = self._setup()

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        # 마크아군의 공격(100 × 1.25[버프_2] = 125) + 홀더의 반응
        # 대미지(공격 굴림 100 × 60% = 60) = 185.
        assert hp_before - hp_after == 185

    def test_reply_labels_bonus_damage_with_holders_name(self):
        """버프_3는 홀더 자신이 아니라 마크아군의 행동에 편승해 발동하므로,
        (도발처럼) 계산식에 "[버프_3: 부여자]" 형태로 누구의 버프_3인지 드러나야
        한다."""
        ctx, manager, holder, marked, enemy = self._setup()

        before = len(ctx.results)
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        reply, calc = format_battle_reply(ctx, marked, ctx.results[before:])

        assert "0.6[버프_3: Sentinel]" in calc

    def test_bonus_damage_respects_holders_own_given_damage_buff(self):
        """버프_3의 추가 대미지도 홀더가 실제로 가하는 대미지이므로, 홀더가
        보유한 [버프_1](주는 대미지 +20%)가 반영되어야 한다."""
        ctx, manager, holder, marked, enemy = self._setup()
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_1")
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        # 마크아군의 공격(125) + 홀더의 반응 대미지(100 × 0.6 × 1.2[버프_1] = 72) = 197.
        assert hp_before - hp_after == 197

    def test_bonus_damage_respects_targets_own_received_damage_buff(self):
        """버프_3의 추가 대미지도 대상이 평소 자신이 공격당할 때 받는 "받는
        대미지" 버프의 영향을 받아야 한다."""
        ctx, manager, holder, marked, enemy = self._setup()
        ctx.buff_container.add(
            _buff_add(
                given_by="적군", applied_to="적군", buff_id="받는대미지감소_테스트"
            )
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        # 마크아군의 공격은 원래도 대상의 받는 대미지 감소 50%를 받는
        # 일반 공격이라 100 × 1.25[버프_2] × 0.5[받는대미지감소] = 62(내림).
        # 홀더의 반응 대미지도 동일하게 대상의 받는 대미지 감소가 적용되어
        # 100 × 0.6 × 0.5 = 30. 합계 92.
        assert hp_before - hp_after == 92

    def test_bonus_damage_ignores_holders_own_taunt_status(self):
        """버프_3의 추가 대미지는 홀더가 스스로 선언한 공격이 아니라 마크아군의
        공격에 편승해 발동하는 반응형 대미지라, 홀더가 다른 적에게 도발당한
        상태여도 도발자가 아니라 마크아군이 실제로 공격한 대상에게 그대로
        꽂혀야 한다(도발의 대상 리다이렉트는 도발당한 캐릭터 본인이 선언한
        공격에만 적용되고, process() 시작 시 그 시점에 존재하는 항목만
        훑으므로 나중에 추가되는 버프_3 반응 대미지는 애초에 리다이렉트 대상이
        아니다)."""
        ctx, manager, holder, marked, enemy = self._setup()
        taunter = CharacterId("도발한적")
        ctx.add_character(
            get_test_preset("도발한적", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            _buff_add(given_by="도발한적", applied_to="Sentinel", buff_id="도발_테스트")
        )

        taunter_hp_before = ctx.characters[taunter].status.curr_hp
        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        taunter_hp_after = ctx.characters[taunter].status.curr_hp
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        assert taunter_hp_before == taunter_hp_after
        assert enemy_hp_before - enemy_hp_after == 185

    def test_no_bonus_when_attacker_is_not_marked(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        unmarked = CharacterId("마크없는아군")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset("Sentinel", atk=100, attack_range=5),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("마크없는아군", atk=100),
            FactionType.ALLY,
            BattlefieldColumnIndex(1),
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )
        ctx.buff_container.add(
            _buff_add(given_by="Sentinel", applied_to="Sentinel", buff_id="버프_3")
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(unmarked, "[공격/적군]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        assert hp_before - hp_after == 100
