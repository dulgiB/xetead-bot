"""
"아군 배려" 패시브 관련 테스트: (A) 아군에게 주는 대미지 감소(상시) +
(B) 지난 라운드에 사거리 내 아군이 맞았다면 이번 라운드 동안 자기 버프 부여.

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/패시브명 대신 일반화된 이름을 쓴다.
"""

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buffs import BuffGivenDamage
from battle.objects.buff.conditions import TargetIsAllyCondition
from battle.objects.buff.models import BuffData
from battle.objects.define import (
    ActionType,
    BattlefieldColumnIndex,
    BuffType,
    FactionType,
    ValueType,
)
from battle.objects.models import CharacterId
from battle.objects.passive_skill.models import (
    PassiveSkillData,
    PassiveSkillTargetType,
    PassiveSkillTrigger,
)
from battle.objects.skill.effects import SkillEffectAddBuff
from battle.practice.context import PracticeBattlefieldContext
from battle.practice.define import (
    PracticeBattleMode,
    PracticeRoundPhase,
    SideType,
)
from battle.practice.round_manager import PracticeRoundManager
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
    """(B) 사거리 이내 자신을 제외한 아군이 **지난 라운드에** 대미지를
    입었다면, 이번 라운드 동안 지속되는 '주는 대미지 +10%' 버프를 자신에게
    부여해야 한다. 자신이 맞은 것만으로는 발동하지 않는다.

    라운드 종료 트리거로 부여하면 같은 on_round_end()가 곧바로 턴을 차감해
    지속시간을 2로 적어 보정해야 하고, 그러면 시트 값이 설명과 한 턴 어긋난다.
    그래서 "라운드 시작 시 지난 라운드 결과로 판정"하는 형태로 표현한다."""

    REWARD_BUFF_ID = "RewardBuff"

    def _make_reward_buff(self) -> BuffData:
        return BuffData(
            id=self.REWARD_BUFF_ID,
            buff_class_name="BuffGivenDamage",
            # 라운드 시작 시점에 부여되므로 설명 그대로 1턴이면 된다 —
            # 그 라운드가 끝날 때 차감되어 사라진다.
            duration_turn_value=1,
            duration_count_value=None,
            duration_count_deduct_condition=None,
            value_type=ValueType.PERCENT,
            value=10,
            condition_=None,
            condition_value=None,
            buff_type=BuffType.BUFF,
            description="",
        )

    def _make_passive(self) -> PassiveSkillData:
        return PassiveSkillData(
            id="PassiveSkill",
            trigger=PassiveSkillTrigger.ROUND_START,
            target_type=PassiveSkillTargetType.SELF,
            effects=[
                SkillEffectAddBuff(
                    value_source=None,
                    value=None,
                    value_type=None,
                    buff_id=self.REWARD_BUFF_ID,
                    buff_add_timing=None,
                    condition_class_name=(
                        "OtherAllyInRangeWasAttackedLastRoundCondition"
                    ),
                )
            ],
            description="",
        )

    def _make_context(self) -> BattlefieldContext:
        return BattlefieldContext(
            buff_dict={self.REWARD_BUFF_ID: self._make_reward_buff()},
            skill_dict={},
            passive_skill_dict={"PassiveSkill": self._make_passive()},
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

    def _finish_round_and_start_next(self, manager: RoundManager) -> None:
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)

    def _has_reward(self, ctx: BattlefieldContext, holder_id: CharacterId) -> bool:
        return any(
            b.id == self.REWARD_BUFF_ID
            for b in ctx.buff_container.get_buffs_by(holder_id, None)
        )

    def test_buff_granted_at_next_round_start_when_ally_in_range_damaged(self):
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

        # 맞은 그 라운드에는 아직 붙지 않는다.
        assert not self._has_reward(ctx, holder_id)

        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)

        assert self._has_reward(ctx, holder_id)

    def test_no_buff_when_no_ally_in_range_was_damaged(self):
        ctx = self._make_context()
        manager = _make_manager(ctx)
        self._add_characters(ctx)
        holder_id = CharacterId("시전자")

        self._finish_round_and_start_next(manager)

        assert not self._has_reward(ctx, holder_id)

    def test_no_buff_when_only_holder_itself_was_damaged(self):
        """사거리 이내 다른 아군은 멀쩡하고 홀더 자신만 맞았다면 발동하지
        않아야 한다(자신은 제외하는 조건)."""
        ctx = self._make_context()
        manager = _make_manager(ctx)
        self._add_characters(ctx)
        holder_id = CharacterId("시전자")

        # 적이 '피해아군' 대신 홀더 자신('시전자')을 공격
        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/시전자]", ctx)
        )
        self._finish_round_and_start_next(manager)

        assert not self._has_reward(ctx, holder_id)

    def test_buff_lasts_exactly_the_round_it_was_granted_in(self):
        """라운드 시작 시 1턴짜리로 붙으므로 그 라운드 내내 유지되다가 라운드
        종료 차감으로 사라진다. 지난 라운드에 아무도 맞지 않았다면 다시
        붙지 않는다."""
        ctx = self._make_context()
        manager = _make_manager(ctx)
        self._add_characters(ctx)
        holder_id = CharacterId("시전자")

        # Round 1: 피해아군이 공격당함
        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/피해아군]", ctx)
        )
        self._finish_round_and_start_next(manager)

        # Round 2: 라운드 시작 시 부여되어 이번 라운드 동안 유지된다.
        assert self._has_reward(ctx, holder_id)
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        assert self._has_reward(ctx, holder_id)

        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        manager.to_phase(RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY)
        assert not self._has_reward(ctx, holder_id)

        # Round 3: 지난 라운드(2)엔 아무도 맞지 않았으므로 다시 붙지 않는다.
        manager.to_phase(RoundPhaseType.ENEMY_PRE_ACTION)
        assert not self._has_reward(ctx, holder_id)

    def test_practice_mode_grants_the_same_single_round_duration(self):
        """대련/상시전투도 본 전투와 같은 라운드 종료 차감을 쓰므로, 라운드
        시작 트리거로 표현한 이 버프는 두 모드에서 같은 1라운드를 간다."""
        ctx = PracticeBattlefieldContext(
            buff_dict={self.REWARD_BUFF_ID: self._make_reward_buff()},
            skill_dict={},
            passive_skill_dict={"PassiveSkill": self._make_passive()},
            mode=PracticeBattleMode.INVESTIGATION,
        )
        manager = PracticeRoundManager(ctx)
        ctx.add_character(
            get_test_preset("시전자", passive_skill_id="PassiveSkill", attack_range=3),
            SideType.SIDE_1,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("피해아군"), SideType.SIDE_1, BattlefieldColumnIndex(2)
        )
        ctx.add_character(
            get_test_preset("적군"), SideType.SIDE_2, BattlefieldColumnIndex(2)
        )
        holder_id = CharacterId("시전자")

        # Round 1: 후공(2팀)이 피해아군을 공격
        manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
        manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
        manager.process_command(
            parse_character_command(CharacterId("적군"), "[공격/피해아군]", ctx)
        )
        manager.end_round()
        assert not self._has_reward(ctx, holder_id)

        # Round 2: 시작 시 부여, 그 라운드 종료와 함께 사라진다.
        manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
        assert self._has_reward(ctx, holder_id)
        manager.to_phase(PracticeRoundPhase.SECOND_MOVER_ACTION)
        manager.end_round()
        assert not self._has_reward(ctx, holder_id)

        # Round 3: 다시 붙지 않아야 한다(본 전투와 동일).
        manager.to_phase(PracticeRoundPhase.FIRST_MOVER_ACTION)
        assert not self._has_reward(ctx, holder_id)
