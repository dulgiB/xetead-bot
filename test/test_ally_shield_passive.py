"""
"아군 배려" 패시브 관련 테스트: (A) 아군에게 주는 대미지 감소(상시) +
(B) 라운드 종료 시점 조건부로 다음 라운드에만 지속되는 자기 버프 부여.

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/패시브명 대신 일반화된 이름을 쓴다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buffs import BuffGivenDamage
from battle.objects.buff.conditions import AllyInRangeWasAttackedCondition, TargetIsAllyCondition
from battle.objects.buff.models import BuffData
from battle.objects.define import ActionType, BattlefieldColumnIndex, FactionType, ValueType
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectAddBuff
from helpers import get_test_preset


def _make_buff_mod_event():
    """PassiveSkillData.from_dict()가 '버프_패시브' 시트 행을 buff_mod_event로
    변환하는 방식(app/battle/objects/passive_skill/models.py)을 그대로 재현."""
    temp = object.__new__(BuffGivenDamage)
    temp.id = "PassiveBuff"
    temp.value = -60
    temp.value_type = ValueType.PERCENT
    temp.condition = TargetIsAllyCondition()
    return temp.create_event()


def _make_manager(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


class TestAllyDamageReduction:
    """(A) 아군에게 주는 대미지가 60% 감소해야 하고, 적에게는 영향이 없어야 한다."""

    def _make_context(self) -> BattlefieldContext:
        passive = PassiveSkillData(
            id="PassiveSkill",
            trigger=PassiveSkillTrigger.ON_ACTION,
            target_type=PassiveSkillTargetType.SELF,
            effects=[],
            description="",
            buff_mod_event=_make_buff_mod_event(),
        )
        return BattlefieldContext(
            buff_dict={}, skill_dict={}, passive_skill_dict={"PassiveSkill": passive}
        )

    def test_damage_to_ally_is_reduced_but_damage_to_enemy_is_not(self):
        ctx = self._make_context()
        manager = _make_manager(ctx)
        holder_id = CharacterId("시전자")
        ally_target_id = CharacterId("아군 대상")
        enemy_target_id = CharacterId("적군 대상")

        ctx.add_character(
            get_test_preset("시전자", passive_skill_id="PassiveSkill", attack_range=3),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군 대상"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )
        ctx.add_character(
            get_test_preset("적군 대상"), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(holder_id, "[공격/아군 대상]", ctx)
        )
        manager.process_command(
            parse_character_command(holder_id, "[공격/적군 대상]", ctx)
        )

        ally_damage = 100 - ctx.characters[ally_target_id].status.curr_hp
        enemy_damage = 100 - ctx.characters[enemy_target_id].status.curr_hp

        # 공격력 5 + 주사위 1d6(1~6) = 6~11. 아군 대상은 -60%(→2~4),
        # 적군 대상은 감소 없음(→6~11)이므로 항상 아군 쪽이 더 작다.
        assert ally_damage < enemy_damage


class TestNextRoundGivenDamageBuffOnAllyInRangeDamaged:
    """(B) 사거리 이내 아군이 그 라운드에 대미지를 입었다면, 다음 라운드에만
    지속되는 '주는 대미지 +10%' 버프를 자신에게 부여해야 한다."""

    REWARD_BUFF_ID = "RewardBuff"

    def _make_context(self) -> BattlefieldContext:
        reward_buff = BuffData(
            id=self.REWARD_BUFF_ID,
            buff_class_name="BuffGivenDamage",
            # ON_ROUND_END 시점에 부여된 버프는 부여되는 그 호출 안에서 즉시
            # deduct_turn()이 한 번 실행되므로, "다음 라운드 1턴"을 보장하려면
            # duration_turn_value를 2로 설정해야 한다.
            duration_turn_value=2,
            duration_count_value=None,
            duration_count_deduct_condition=None,
            value_type=ValueType.PERCENT,
            value=10,
            condition_=None,
            condition_value=None,
            is_debuff=False,
            description="",
        )
        passive = PassiveSkillData(
            id="PassiveSkill",
            trigger=PassiveSkillTrigger.ROUND_END,
            target_type=PassiveSkillTargetType.SELF,
            effects=[
                SkillEffectAddBuff(
                    value_source=None,
                    value=None,
                    value_type=None,
                    buff_id=self.REWARD_BUFF_ID,
                    buff_add_timing=None,
                    condition_class_name="AllyInRangeWasAttackedCondition",
                )
            ],
            description="",
        )
        return BattlefieldContext(
            buff_dict={self.REWARD_BUFF_ID: reward_buff},
            skill_dict={},
            passive_skill_dict={"PassiveSkill": passive},
        )

    def _add_characters(self, ctx: BattlefieldContext) -> None:
        ctx.add_character(
            get_test_preset("시전자", passive_skill_id="PassiveSkill", attack_range=3),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("피해아군"), FactionType.ALLY, BattlefieldColumnIndex(2)
        )
        ctx.add_character(
            get_test_preset("적군"), FactionType.ENEMY, BattlefieldColumnIndex(2)
        )

    def test_buff_granted_after_round_end_when_ally_in_range_damaged(self):
        ctx = self._make_context()
        manager = _make_manager(ctx)
        self._add_characters(ctx)
        holder_id = CharacterId("시전자")

        # 적이 사거리 이내(COL3)의 피해아군을 공격 → damaged_this_round에 기록됨
        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/피해아군]", ctx)
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

        assert any(
            b.id == self.REWARD_BUFF_ID
            for b in ctx.buff_container.get_buffs_by(holder_id, None)
        )

    def test_no_buff_when_no_ally_in_range_was_damaged(self):
        ctx = self._make_context()
        manager = _make_manager(ctx)
        self._add_characters(ctx)
        holder_id = CharacterId("시전자")

        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

        assert not any(
            b.id == self.REWARD_BUFF_ID
            for b in ctx.buff_container.get_buffs_by(holder_id, None)
        )

    def test_buff_expires_after_the_following_round_ends(self):
        """부여 라운드 종료 시 즉시 1턴이 깎이더라도, 다음 라운드 동안은
        살아있고 그 다음 라운드가 끝나면 사라져야 한다."""
        ctx = self._make_context()
        manager = _make_manager(ctx)
        self._add_characters(ctx)
        holder_id = CharacterId("시전자")

        # Round 1: 피해아군이 공격당함 → 라운드 종료 시 보상 버프 부여
        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/피해아군]", ctx)
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        assert any(
            b.id == self.REWARD_BUFF_ID
            for b in ctx.buff_container.get_buffs_by(holder_id, None)
        )

        # Round 2: 아무도 공격당하지 않음 — 이번 라운드 동안은 보상 버프가 유지되어야 함
        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        assert any(
            b.id == self.REWARD_BUFF_ID
            for b in ctx.buff_container.get_buffs_by(holder_id, None)
        )

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)

        # Round 2 종료 시점에 소멸해야 한다.
        assert not any(
            b.id == self.REWARD_BUFF_ID
            for b in ctx.buff_container.get_buffs_by(holder_id, None)
        )
