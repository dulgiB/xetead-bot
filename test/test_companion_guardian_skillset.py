"""동료 소환/가디언 스킬셋(패시브+코스트2+코스트3) 통합 테스트.

실제 '버프'/'스킬_캐릭터'/'스킬_패시브' 시트 행과 동일한 형태(각 데이터클래스의
from_dict())로 로드했을 때 의도대로 동작하는지 확인한다. 캐릭터/스킬/버프 id는
실제 스프레드시트의 고유명사를 코드에 노출하지 않도록 모두 일반화한 이름
(CompanionGuardian, PassiveSkill, Cost2Skill, Cost3Skill, CompanionBuff1,
CompanionBuff2)을 쓴다.

- 패시브(PassiveSkill): 전투 시작 시 동료를 소환(최대 체력 20%)하고, 동료가 살아
  있는 한 받는 대미지를 절반씩 나누고 반격하는 [CompanionBuff1] 버프를 자신에게 부여한다.
- 코스트 2 스킬(Cost2Skill): 동료가 있으면 200% 대미지 + 도발, 없으면 도발 없이
  250% 대미지.
- 코스트 3 스킬(Cost3Skill): 지정한 열 전체에 80% 대미지 + 1턴 도발. 동료가 있으면
  동료 체력 10을 소모해 자신에게 2턴간 [CompanionBuff2](받는 대미지 -20%)를 부여하고,
  없으면 동료를 최대 체력 10%로 재소환한다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import PassiveSkillData
from battle.objects.skill.effects import SkillEffectDamage
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

OWNER = CharacterId("CompanionGuardian")


def _companion_id(ctx: BattlefieldContext) -> CharacterId:
    companion_id = ctx.find_companion_id(OWNER)
    assert companion_id is not None
    return companion_id


def _buff_dict() -> dict[str, BuffData]:
    return {
        "CompanionBuff1": BuffData.from_dict(
            {
                "id": "CompanionBuff1",
                "buff_name": "BuffCompanionGuardian",
                "duration_turn_value": "",
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": (
                    "동료가 필드에 살아 있는 한 받는 대미지를 절반씩 나누고,"
                    " 자신을 공격한 대상에게 공격 굴림 80%만큼 반격한다."
                ),
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "CompanionBuff2": BuffData.from_dict(
            {
                "id": "CompanionBuff2",
                "buff_name": "BuffReceivedDamage",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": -20,
                "value_type": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": "받는 대미지가 20% 감소한다.",
                "is_debuff": False,
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
                "description": "적의 공격과 부가 효과를 자신에게 유도",
                "is_debuff": True,
                "max_stack": "",
            }
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
                "effect_0": "SkillEffectDamageOrTauntIfCompanionAbsent",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "공격 굴림값",
                "value_0": 200,
                "value_type_0": "퍼센트",
                "buff_id_0": "도발",
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
                    "대상에게 공격 굴림 200%만큼 대미지를 입히고, 동료가 있다면"
                    " 대상에게 1턴간 도발을 부여한다. 동료가 없다면 도발 없이"
                    " 공격 굴림 250%만큼 대미지를 입힌다."
                ),
            }
        ),
        "Cost3Skill": SkillData.from_dict(
            {
                "id": "Cost3Skill",
                "target_rule": "SkillTargetRuleColumn",
                "target_count": 1,
                "cost": 3,
                "effect_0": "SkillEffectDamage",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "공격 굴림값",
                "value_0": 80,
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
                "effect_2": "SkillEffectSpendCompanionHpOrSummon",
                "condition_2": "",
                "condition_value_2": "",
                "value_source_2": "고정값",
                "value_2": 10,
                "value_type_2": "정수",
                "buff_id_2": "CompanionBuff2",
                "buff_stack_cap_2": "",
                "target_override_2": "자신",
                "description": (
                    "사거리 내에서 열 1개를 지정한다. 범위 내의 모든 적에게 공격"
                    " 굴림 80%만큼 대미지를 입히고 1턴간 도발을 부여한다. 동료가"
                    " 있다면 동료의 체력을 10 소모해 자신에게 2턴간 [CompanionBuff2]를"
                    " 부여하고, 없다면 동료가 최대 체력 10%로 다시 나타난다."
                ),
            }
        ),
        "고정대미지스킬": SkillData(
            id="고정대미지스킬",
            target_rule="SkillTargetRuleNamed",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=60,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
                )
            ],
            description="",
        ),
        "적군광역기": SkillData(
            id="적군광역기",
            target_rule="SkillTargetRuleColumn",
            target_count=1,
            cost=0,
            effects=[
                SkillEffectDamage(
                    value_source=ValueSourceType.FIXED,
                    value=10,
                    value_type=ValueType.INTEGER,
                    buff_id=None,
                    buff_add_timing=None,
                )
            ],
            description="",
        ),
    }


def _passive_skill_dict() -> dict[str, PassiveSkillData]:
    return {
        "PassiveSkill": PassiveSkillData.from_dict(
            {
                "id": "PassiveSkill",
                "trigger": "전투 시작",
                "target_type": "자신",
                "buff_id": "",
                "effect_0": "SkillEffectSummonCompanionAtBattleStart",
                "value_source_0": "",
                "value_0": 20,
                "value_type_0": "정수",
                "buff_id_0": "CompanionBuff1",
                "target_override_0": "",
                "condition_0": "",
                "condition_value_0": "",
                "effect_1": "SkillEffectAddBuff",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "CompanionBuff1",
                "target_override_1": "",
                "condition_1": "",
                "condition_value_1": "",
                "description": (
                    "전투를 시작할 때 동료가 참여한다. 동료는 자신 최대 체력의"
                    " 20%만큼 체력을 가지며, 위치는 자신과 같은 것으로 취급한다."
                    " 동료는 자신이 받는 모든 대미지의 50%를 나누어 받으며,"
                    " 동료가 필드에 남아 있는 한 자신에게 [반격]이 부여된 것으로"
                    " 취급한다."
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


def _add_owner(ctx: BattlefieldContext, **kwargs) -> None:
    ctx.add_character(
        get_test_preset(
            OWNER.name,
            passive_skill_id="PassiveSkill",
            skill_1_id="Cost2Skill",
            skill_2_id="Cost3Skill",
            **kwargs,
        ),
        FactionType.ALLY,
        BattlefieldColumnIndex(0),
    )


class TestSummonAtBattleStart:
    def test_companion_spawns_with_20_percent_max_hp(self):
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.add_character(
            get_test_preset("적군", max_hp=1000), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        ctx.on_battle_start()
        companion_id = _companion_id(ctx)

        companion = ctx.characters[companion_id]
        assert companion.status.curr_hp == 40
        assert companion.faction == FactionType.ALLY
        assert ctx.find_character_position(companion_id) == ctx.find_character_position(OWNER)

    def test_field_display_shows_companion_hp_next_to_guardian_buff(self):
        """[CompanionBuff1] 버프 표시줄에만 동료 체력이 "(이름: 현재/최대)" 형식으로
        붙어야 한다."""
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.add_character(
            get_test_preset("적군", max_hp=1000), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        ctx.on_battle_start()
        companion_id = _companion_id(ctx)
        ctx.characters[companion_id].status.curr_hp = 33

        assert f"[CompanionBuff1] ({companion_id.name}: 33/40)" in str(ctx)

    def test_does_not_respawn_if_already_alive(self):
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.on_battle_start()
        companion_id = _companion_id(ctx)
        first_companion_hp = ctx.characters[companion_id].status.curr_hp

        ctx.characters[companion_id].status.curr_hp = 5
        ctx.on_battle_start()

        # 이미 살아 있으므로(체력 1 이상) 두 번째 호출은 재소환하지 않는다.
        assert ctx.characters[companion_id].status.curr_hp == 5
        assert first_companion_hp == 40

    def test_companion_does_not_occupy_a_column_slot(self):
        """동료는 position_map 슬롯을 차지하지 않으므로, owner의 열이 이미
        가득 차 있어도(3/3) 소환에 지장이 없어야 한다."""
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.add_character(
            get_test_preset("아군2"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("아군3"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        assert ctx.try_find_empty_slot(FactionType.ALLY, BattlefieldColumnIndex(0)) is None

        ctx.on_battle_start()
        companion_id = _companion_id(ctx)

        assert companion_id in ctx.characters
        assert ctx.characters[companion_id].status.curr_hp == 40
        assert ctx.find_character_position(companion_id) == BattlefieldColumnIndex(0)
        # 슬롯 자체는 여전히 3/3 그대로다 — 동료가 슬롯을 차지하지 않았다는 뜻.
        assert ctx.try_find_empty_slot(FactionType.ALLY, BattlefieldColumnIndex(0)) is None
        assert companion_id not in ctx.position_map[FactionType.ALLY][BattlefieldColumnIndex(0)].values()

    def test_enemy_column_aoe_splits_as_single_hit_on_owner(self):
        """동료가 position_map에 없어도 owner의 열을 노리는 열 대상(AOE)
        스킬에 맞긴 하지만, 동료를 독립된 별도 대상으로 추가 포함하지는
        않는다 — owner만 맞은 것으로 취급하고, 그 1회분 대미지를 가디언
        버프가 owner/동료에게 절반씩 나눠 준다(단일 대상 공격과 동일한
        분담 경로). 동료를 열 대상에 별도로 포함시키면 owner와 동료가
        각자 전체 대미지를 따로 맞아 실질 피해량이 2배가 되므로 피한다."""
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.add_character(
            get_test_preset("적군", max_hp=1000, skill_1_id="적군광역기"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.on_battle_start()
        companion_id = _companion_id(ctx)
        manager = _setup_ally_phase(ctx)
        enemy = CharacterId("적군")

        owner_hp_before = ctx.characters[OWNER].status.curr_hp
        companion_hp_before = ctx.characters[companion_id].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
        manager.process_command(parse_character_command(enemy, "[적군광역기/1열]", ctx))
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        # 고정 10 대미지 1회분을 절반씩(5/5) 나눠 받는다 — 합계는 원래
        # 1회분(10) 그대로다.
        assert owner_hp_before - ctx.characters[OWNER].status.curr_hp == 5
        assert companion_hp_before - ctx.characters[companion_id].status.curr_hp == 5
        # owner가 실제로 맞았으므로 반격은 정상적으로 발동해야 한다.
        assert ctx.characters[enemy].status.curr_hp == 1000 - 80


class TestCost2Skill:
    def test_deals_200_percent_and_grants_taunt_when_companion_alive(self):
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.add_character(
            get_test_preset("적군", max_hp=1000), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.on_battle_start()
        manager = _setup_ally_phase(ctx)
        target = CharacterId("적군")

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(parse_character_command(OWNER, "[Cost2Skill/적군]", ctx))
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 200
        assert any(
            b.id == "도발" for b in ctx.buff_container.get_buffs_by(target, None)
        )

    def test_deals_250_percent_without_taunt_when_companion_absent(self):
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.add_character(
            get_test_preset("적군", max_hp=1000), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        # on_battle_start()를 호출하지 않아 동료가 존재하지 않는 상태를 재현한다.
        manager = _setup_ally_phase(ctx)
        target = CharacterId("적군")

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(parse_character_command(OWNER, "[Cost2Skill/적군]", ctx))
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 250
        assert not any(
            b.id == "도발" for b in ctx.buff_container.get_buffs_by(target, None)
        )


class TestCost3Skill:
    def _make_ready_context(self):
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.add_character(
            get_test_preset("적군", max_hp=1000), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        return ctx

    def test_spends_companion_hp_and_grants_shield_when_companion_alive(self):
        ctx = self._make_ready_context()
        ctx.on_battle_start()
        companion_id = _companion_id(ctx)
        manager = _setup_ally_phase(ctx)
        target = CharacterId("적군")

        hp_before = ctx.characters[target].status.curr_hp
        companion_hp_before = ctx.characters[companion_id].status.curr_hp
        manager.process_command(parse_character_command(OWNER, "[Cost3Skill/1열]", ctx))
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 80
        assert any(
            b.id == "도발" for b in ctx.buff_container.get_buffs_by(target, None)
        )
        assert ctx.characters[companion_id].status.curr_hp == companion_hp_before - 10
        assert any(
            b.id == "CompanionBuff2" for b in ctx.buff_container.get_buffs_by(OWNER, None)
        )

    def test_companion_hp_clamps_to_zero_when_below_spend_amount(self):
        ctx = self._make_ready_context()
        ctx.on_battle_start()
        companion_id = _companion_id(ctx)
        ctx.characters[companion_id].status.curr_hp = 4
        manager = _setup_ally_phase(ctx)

        manager.process_command(parse_character_command(OWNER, "[Cost3Skill/1열]", ctx))

        assert ctx.characters[companion_id].status.curr_hp == 0
        assert any(
            b.id == "CompanionBuff2" for b in ctx.buff_container.get_buffs_by(OWNER, None)
        )

    def test_resummons_companion_at_10_percent_when_dead(self):
        ctx = self._make_ready_context()
        # 패시브가 전투 시작 시 이미 동료를 소환해 이름을 확정해 둔 상태에서,
        # 동료가 대미지로 죽어 부재가 된 경우를 재현한다(코스트 3의 재소환
        # 분기는 이 등록을 그대로 재사용하므로, 최초 소환 자체가 없었던
        # 상태는 실제 플레이에서 발생하지 않는다).
        ctx.on_battle_start()
        companion_id = _companion_id(ctx)
        ctx.characters[companion_id].status.curr_hp = 0
        manager = _setup_ally_phase(ctx)
        target = CharacterId("적군")

        hp_before = ctx.characters[target].status.curr_hp
        manager.process_command(parse_character_command(OWNER, "[Cost3Skill/1열]", ctx))
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 80
        assert ctx.characters[companion_id].status.curr_hp == 20  # 200 * 10%
        assert not any(
            b.id == "CompanionBuff2" for b in ctx.buff_container.get_buffs_by(OWNER, None)
        )


class TestCompanionGuardianSplitAndCounter:
    def _make_ready_context(self):
        ctx = _make_context()
        _add_owner(ctx, max_hp=200, atk=100)
        ctx.add_character(
            get_test_preset("적군", max_hp=1000, skill_1_id="고정대미지스킬"),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        return ctx

    def test_incoming_damage_is_split_and_counter_hits_attacker(self):
        ctx = self._make_ready_context()
        ctx.on_battle_start()
        companion_id = _companion_id(ctx)
        manager = _setup_ally_phase(ctx)
        enemy = CharacterId("적군")

        owner_hp_before = ctx.characters[OWNER].status.curr_hp
        companion_hp_before = ctx.characters[companion_id].status.curr_hp
        enemy_hp_before = ctx.characters[enemy].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
        manager.process_command(
            parse_character_command(enemy, "[고정대미지스킬/CompanionGuardian]", ctx)
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        owner_damage = owner_hp_before - ctx.characters[OWNER].status.curr_hp
        companion_damage = companion_hp_before - ctx.characters[companion_id].status.curr_hp
        enemy_damage = enemy_hp_before - ctx.characters[enemy].status.curr_hp

        # 고정 100 대미지를 절반씩(50/50) 나눠 받는다.
        assert owner_damage == 30
        assert companion_damage == 30
        # 반격: 공격 굴림 80% (milestone_n=0이므로 atk=100 그대로 굴림 → 80).
        assert enemy_damage == 80

    def test_no_split_or_counter_when_companion_absent(self):
        ctx = self._make_ready_context()
        # on_battle_start()를 호출하지 않아 동료가 없는 상태에서 시작한다.
        manager = _setup_ally_phase(ctx)
        enemy = CharacterId("적군")

        owner_hp_before = ctx.characters[OWNER].status.curr_hp
        enemy_hp_before = ctx.characters[enemy].status.curr_hp

        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
        manager.process_command(
            parse_character_command(enemy, "[고정대미지스킬/CompanionGuardian]", ctx)
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)

        assert owner_hp_before - ctx.characters[OWNER].status.curr_hp == 60
        assert enemy_hp_before - ctx.characters[enemy].status.curr_hp == 0
