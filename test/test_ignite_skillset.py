"""
"주는 대미지 감소" 패시브 + 코스트 2 스킬(공격 굴림 기반 대미지 + [발화] 디버프
부여) 스킬셋에 대한 테스트. [발화]는 부여 시점 대상의 열을 스냅샷해두었다가,
지속시간이 끝나는(0턴이 되는) 라운드 종료 시점에 대상이 그 열에 그대로
있으면 부여자 공격 굴림 기반 대미지를 입히는 디버프이며, 서로 다른 열로
부여되면 동시에 여러 개 유지될 수 있다.

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/스킬/패시브명 대신 일반화된 이름을
쓴다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.buff.buffs import BuffGivenDamage
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    FactionType,
    ValueSourceType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import (
    SkillEffectAddBuffAtTargetColumn,
    SkillEffectDamage,
)
from battle.objects.skill.models import SkillData
from helpers import get_test_preset

IGNITE_BUFF_ID = "Ignite"
COST2_SKILL_ID = "Cost2Skill"
PASSIVE_SKILL_ID = "PassiveSkill"


def make_ignite_buff_data(duration_turn_value: int = 2) -> BuffData:
    return BuffData(
        id=IGNITE_BUFF_ID,
        buff_class_name="BuffIgnite",
        duration_turn_value=duration_turn_value,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.INTEGER,
        value=0,
        condition_=None,
        condition_value=None,
        is_debuff=True,
        description="",
    )


def make_cost2_skill() -> SkillData:
    """대상에게 공격 굴림 230% 대미지를 입히고, 대상의 현재 위치를 기준으로
    2턴간 [발화: X열]을 부여한다."""
    return SkillData(
        id=COST2_SKILL_ID,
        target_rule="SkillTargetRuleNamed",
        target_count=1,
        cost=2,
        effects=[
            SkillEffectDamage(
                ValueSourceType.STAT_ATK_ROLL, 230, ValueType.PERCENT, None, None
            ),
            SkillEffectAddBuffAtTargetColumn(
                value_source=None,
                value=None,
                value_type=None,
                buff_id=IGNITE_BUFF_ID,
                buff_add_timing=None,
            ),
        ],
        description="",
    )


def _make_buff_mod_event(value: int):
    """PassiveSkillData.from_dict()가 '버프_패시브' 시트 행을 buff_mod_event로
    변환하는 방식(app/battle/objects/passive_skill/models.py)을 그대로 재현."""
    temp = object.__new__(BuffGivenDamage)
    temp.id = "PassiveBuff"
    temp.value = value
    temp.value_type = ValueType.PERCENT
    temp.condition = None
    return temp.create_event()


def make_passive_skill_data() -> PassiveSkillData:
    """자신이 주는 대미지가 30% 감소한다."""
    return PassiveSkillData(
        id=PASSIVE_SKILL_ID,
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[],
        description="",
        buff_mod_event=_make_buff_mod_event(-30),
    )


def make_context(
    ignite_duration_turn_value: int = 2,
    with_passive: bool = False,
) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict={IGNITE_BUFF_ID: make_ignite_buff_data(ignite_duration_turn_value)},
        skill_dict={COST2_SKILL_ID: make_cost2_skill()},
        passive_skill_dict={PASSIVE_SKILL_ID: make_passive_skill_data()}
        if with_passive
        else None,
    )


def setup_ally_phase(context: BattlefieldContext) -> RoundManager:
    manager = RoundManager(context)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ALLY_ACTION
        )
    )
    return manager


class TestGivenDamageReductionPassive:
    """자신이 주는 대미지가 30% 감소하는 패시브."""

    def test_damage_dealt_is_reduced_by_30_percent(self):
        ctx = make_context(with_passive=True)
        manager = setup_ally_phase(ctx)
        attacker_id = CharacterId("공격수")
        target_id = CharacterId("대상")

        # ATK를 키워 -30%(×0.7) 배율이 1d6 변동을 항상 압도하도록 한다.
        # 무버프딜: ATK+1d6 = 31~36. -30%: floor(31*0.7)=21 ~ floor(36*0.7)=25.
        # 21~25 < 31~36 이므로 항상 감소된 쪽이 더 작다.
        ctx.add_character(
            get_test_preset("공격수", atk=30, passive_skill_id=PASSIVE_SKILL_ID),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상", max_hp=1000),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx_no_passive = make_context(with_passive=False)
        manager_no_passive = setup_ally_phase(ctx_no_passive)
        ctx_no_passive.add_character(
            get_test_preset("공격수", atk=30),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx_no_passive.add_character(
            get_test_preset("대상", max_hp=1000),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )

        manager.process_command(
            parse_character_command(attacker_id, "[공격/대상]", ctx)
        )
        damage_with_passive = 1000 - ctx.characters[target_id].status.curr_hp

        manager_no_passive.process_command(
            parse_character_command(attacker_id, "[공격/대상]", ctx_no_passive)
        )
        damage_without_passive = (
            1000 - ctx_no_passive.characters[target_id].status.curr_hp
        )

        assert damage_with_passive < damage_without_passive


class TestCost2SkillDamageAndDebuff:
    """코스트 2 스킬: 대미지 + 대상 현재 위치 기준 [발화] 부여."""

    def _add_characters(
        self, ctx: BattlefieldContext, target_column: BattlefieldColumnIndex
    ) -> None:
        ctx.add_character(
            get_test_preset("시전자", skill_1_id=COST2_SKILL_ID),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(get_test_preset("대상"), FactionType.ENEMY, target_column)

    def test_deals_damage_and_applies_ignite_at_targets_current_column(self):
        ctx = make_context()
        manager = setup_ally_phase(ctx)
        caster_id = CharacterId("시전자")
        target_id = CharacterId("대상")
        self._add_characters(ctx, BattlefieldColumnIndex(2))

        manager.process_command(
            parse_character_command(caster_id, "[Cost2Skill/대상]", ctx)
        )

        assert ctx.characters[target_id].status.curr_hp < 100
        ignite = ctx.buff_container.get_buff(target_id, IGNITE_BUFF_ID)
        assert ignite is not None
        assert ignite.value == BattlefieldColumnIndex(2).value
        assert ignite.given_by == caster_id


class TestIgniteStacksAcrossDifferentColumns:
    """서로 다른 열에 대해서는 [발화]가 중첩 가능해야 하고, 같은 열이면
    재부여 시 지속시간만 갱신되어야 한다."""

    def test_different_columns_coexist_simultaneously(self):
        ctx = make_context()
        caster_id = CharacterId("시전자")
        target_id = CharacterId("대상")
        ctx.add_character(
            get_test_preset("시전자"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )

        ctx.buff_container.add(
            BuffAddData(
                given_by=caster_id,
                applied_to=target_id,
                buff_id=IGNITE_BUFF_ID,
                value_override=BattlefieldColumnIndex(2).value,
            )
        )
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster_id,
                applied_to=target_id,
                buff_id=IGNITE_BUFF_ID,
                value_override=BattlefieldColumnIndex(3).value,
            )
        )

        buffs = [
            b
            for b in ctx.buff_container.get_buffs_by(target_id, None)
            if b.id == IGNITE_BUFF_ID
        ]
        assert len(buffs) == 2
        assert {b.value for b in buffs} == {
            BattlefieldColumnIndex(2).value,
            BattlefieldColumnIndex(3).value,
        }

    def test_same_column_reapply_refreshes_duration_without_duplicating(self):
        ctx = make_context()
        caster_id = CharacterId("시전자")
        target_id = CharacterId("대상")
        ctx.add_character(
            get_test_preset("시전자"), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("대상"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )

        ctx.buff_container.add(
            BuffAddData(
                given_by=caster_id,
                applied_to=target_id,
                buff_id=IGNITE_BUFF_ID,
                value_override=BattlefieldColumnIndex(2).value,
            )
        )
        ignite = ctx.buff_container.get_buff(target_id, IGNITE_BUFF_ID)
        ignite.duration.remaining_turns = 1

        ctx.buff_container.add(
            BuffAddData(
                given_by=caster_id,
                applied_to=target_id,
                buff_id=IGNITE_BUFF_ID,
                value_override=BattlefieldColumnIndex(2).value,
            )
        )

        buffs = [
            b
            for b in ctx.buff_container.get_buffs_by(target_id, None)
            if b.id == IGNITE_BUFF_ID
        ]
        assert len(buffs) == 1
        assert buffs[0].duration.remaining_turns == 2


class TestIgniteExpireDamage:
    """[발화]가 만료되는(0턴이 되는) 라운드 종료 시점에 대상이 저장된 열에
    있으면 부여자 공격 굴림 150% 대미지를 입혀야 한다."""

    def _setup(
        self, atk: int = 30, target_hp: int = 1000
    ) -> tuple[BattlefieldContext, RoundManager, CharacterId, CharacterId]:
        ctx = make_context()
        caster_id = CharacterId("시전자")
        target_id = CharacterId("대상")
        ctx.add_character(
            get_test_preset("시전자", atk=atk),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("대상", max_hp=target_hp),
            FactionType.ENEMY,
            BattlefieldColumnIndex(2),
        )
        manager = RoundManager(ctx)
        return ctx, manager, caster_id, target_id

    def _grant_ignite(
        self, ctx: BattlefieldContext, caster_id: CharacterId, target_id: CharacterId
    ) -> None:
        ctx.buff_container.add(
            BuffAddData(
                given_by=caster_id,
                applied_to=target_id,
                buff_id=IGNITE_BUFF_ID,
                value_override=BattlefieldColumnIndex(2).value,
            )
        )

    def test_no_damage_before_expiring_round(self):
        ctx, manager, caster_id, target_id = self._setup()
        self._grant_ignite(ctx, caster_id, target_id)

        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

        assert ctx.characters[target_id].status.curr_hp == 1000
        ignite = ctx.buff_container.get_buff(target_id, IGNITE_BUFF_ID)
        assert ignite is not None
        assert ignite.duration.remaining_turns == 1

    def test_deals_damage_on_expiring_round_when_target_still_in_column(self):
        ctx, manager, caster_id, target_id = self._setup()
        self._grant_ignite(ctx, caster_id, target_id)

        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

        assert ctx.characters[target_id].status.curr_hp < 1000
        assert ctx.buff_container.get_buff(target_id, IGNITE_BUFF_ID) is None

    def test_no_damage_when_target_left_the_column_before_expiry(self):
        ctx, manager, caster_id, target_id = self._setup()
        self._grant_ignite(ctx, caster_id, target_id)

        ctx.move_character_to(target_id, BattlefieldColumnIndex(3))

        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

        assert ctx.characters[target_id].status.curr_hp == 1000
        assert ctx.buff_container.get_buff(target_id, IGNITE_BUFF_ID) is None
