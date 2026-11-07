"""
에너미 특성 패시브의 부품 테스트.

- 공격한 대상의 버프를 모두 해제(BuffStripBuffsOnHit)
- 같은 라운드에 같은 대상을 거듭 때리면 추가 대미지
  (TargetAlreadyAttackedThisRoundCondition + BuffGivenDamage)
- 거리가 2 이상인 대상을 칠 때 공격력 증가
  (TargetAtLeastDistanceCondition + BuffAtk)
- 이동하지 않은 대상을 칠 때 공격력 증가
  (TargetDidNotMoveThisTurnCondition + BuffAtk)

CLAUDE.md 정책에 따라 실제 캠페인 캐릭터/패시브명 대신 일반화된 이름을 쓴다.
"""

from typing import Optional

from battle.core.battlefield_context import BattlefieldContext
from battle.core.commands.admin import ChangePhaseCommand
from battle.core.commands.define import RoundPhaseType
from battle.core.commands.parser import parse_character_command
from battle.core.round_manager import RoundManager
from battle.objects.buff.buff_base import BuffAddData, BuffBase, BuffUid
from battle.objects.buff.buffs import (
    BuffAtk,
    BuffGivenDamage,
    BuffStripBuffsOnHit,
)
from battle.objects.buff.conditions import (
    Condition,
    TargetAlreadyAttackedThisRoundCondition,
    TargetAtLeastDistanceCondition,
    TargetDidNotMoveThisTurnCondition,
)
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
from helpers import get_test_preset

HOLDER = CharacterId("보유자")
TARGET = CharacterId("대상")
OTHER = CharacterId("다른 대상")
TAUNTER = CharacterId("도발자")


def _buff_mod_passive(
    buff_class: type[BuffBase],
    *,
    value: int = 0,
    value_type: Optional[ValueType] = None,
    condition: Optional[Condition] = None,
) -> PassiveSkillData:
    """PassiveSkillData.from_dict()가 '버프_패시브' 행을 buff_mod_event로
    바꾸는 방식을 그대로 재현한다."""
    template = buff_class._create_bare(
        id_="PassiveBuff",
        uid=BuffUid(HOLDER, HOLDER, buff_class.__name__),
        given_by=HOLDER,
        applied_to=HOLDER,
        value=value,
        value_type=value_type,
        condition=condition,
    )
    return PassiveSkillData(
        id="PassiveSkill",
        trigger=PassiveSkillTrigger.ON_ACTION,
        target_type=PassiveSkillTargetType.SELF,
        effects=[],
        description="",
        buff_mod_event=template.create_event(),
    )


def _buff_data(buff_id: str, buff_class_name: str, buff_type: BuffType) -> BuffData:
    return BuffData(
        id=buff_id,
        buff_class_name=buff_class_name,
        duration_turn_value=3,
        duration_count_value=None,
        duration_count_deduct_condition=None,
        value_type=ValueType.PERCENT,
        value=0,
        condition_=None,
        condition_value=None,
        buff_type=buff_type,
        description="",
    )


def _context(passive: PassiveSkillData, **kwargs) -> BattlefieldContext:
    return BattlefieldContext(
        buff_dict=kwargs.get("buff_dict", {}),
        skill_dict={},
        passive_skill_dict={"PassiveSkill": passive},
    )


def _manager(ctx: BattlefieldContext) -> RoundManager:
    manager = RoundManager(ctx)
    manager.process_command(
        ChangePhaseCommand(
            type_=ActionType.ADMIN, target_phase=RoundPhaseType.ENEMY_PRE_ACTION
        )
    )
    return manager


def _add(ctx, name, faction, column, **kwargs):
    ctx.add_character(
        get_test_preset(name, **kwargs), faction, BattlefieldColumnIndex(column)
    )


def _damage_taken(ctx: BattlefieldContext, char_id: CharacterId) -> int:
    return 100 - ctx.characters[char_id].status.curr_hp


class TestStripBuffsOnHit:
    def _setup(self):
        ctx = _context(
            _buff_mod_passive(BuffStripBuffsOnHit),
            buff_dict={
                "버프_1": _buff_data("버프_1", "BuffReceivedDamage", BuffType.BUFF),
                "디버프_1": _buff_data(
                    "디버프_1", "BuffReceivedDamage", BuffType.DEBUFF
                ),
                "마커_1": _buff_data("마커_1", "BuffReceivedDamage", BuffType.NEUTRAL),
            },
        )
        manager = _manager(ctx)
        _add(ctx, "보유자", FactionType.ALLY, 0, passive_skill_id="PassiveSkill")
        _add(ctx, "대상", FactionType.ENEMY, 0)
        _add(ctx, "다른 대상", FactionType.ENEMY, 0)
        # 같은 부여자·같은 클래스면 하나로 합쳐지므로 부여자를 나눈다.
        givers = {"버프_1": TARGET, "디버프_1": HOLDER, "마커_1": OTHER}
        for target in (TARGET, OTHER):
            for buff_id, giver in givers.items():
                ctx.buff_container.add(
                    BuffAddData(given_by=giver, applied_to=target, buff_id=buff_id)
                )
        return ctx, manager

    def _ids(self, ctx, char_id):
        return {b.id for b in ctx.buff_container.get_buffs_by(char_id, None)}

    def test_only_buffs_of_the_attacked_target_are_removed(self):
        ctx, manager = self._setup()
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))

        assert "버프_1" not in self._ids(ctx, TARGET)
        assert {"디버프_1", "마커_1"} <= self._ids(ctx, TARGET)
        # 공격받지 않은 쪽은 그대로다.
        assert "버프_1" in self._ids(ctx, OTHER)
        log_text = " ".join(e.result for r in ctx.results for e in r.log_entries)
        assert "모든 버프 해제" in log_text

    def test_holder_own_passive_survives(self):
        ctx, manager = self._setup()
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))
        assert any(
            b.id == "PassiveSkill"
            for b in ctx.buff_container.get_buffs_by(HOLDER, None)
        )


class TestBonusOnRepeatedHitInSameRound:
    def _setup(self):
        ctx = _context(
            _buff_mod_passive(
                BuffGivenDamage,
                value=100,
                value_type=ValueType.PERCENT,
                condition=TargetAlreadyAttackedThisRoundCondition(),
            )
        )
        manager = _manager(ctx)
        # 공격력 0 + 굴림 최대 6이라도 두 번째 타격은 2배여야 한다.
        _add(ctx, "보유자", FactionType.ALLY, 0, passive_skill_id="PassiveSkill")
        _add(ctx, "대상", FactionType.ENEMY, 0)
        _add(ctx, "다른 대상", FactionType.ENEMY, 0)
        return ctx, manager

    def test_second_hit_on_same_target_gets_bonus(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(HOLDER, "[공격/대상 - 공격/대상]", ctx)
        )
        # 첫 타 5+3=8, 두 번째 타 8×2=16.
        assert _damage_taken(ctx, TARGET) == 8 + 16

    def test_hits_on_different_targets_do_not_count(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(HOLDER, "[공격/대상 - 공격/다른 대상]", ctx)
        )
        assert _damage_taken(ctx, TARGET) == 8
        assert _damage_taken(ctx, OTHER) == 8

    def test_count_resets_next_round(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))
        ctx.on_start_round()
        ctx.characters[HOLDER].status.curr_cost = 3
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))
        assert _damage_taken(ctx, TARGET) == 16


class TestAtkAgainstDistantTarget:
    def _setup(self, holder_faction=FactionType.ALLY):
        ctx = _context(
            _buff_mod_passive(
                BuffAtk,
                value=5,
                value_type=ValueType.INTEGER,
                condition=TargetAtLeastDistanceCondition(value=2),
            )
        )
        manager = _manager(ctx)
        target_faction = (
            FactionType.ENEMY
            if holder_faction == FactionType.ALLY
            else FactionType.ALLY
        )
        _add(ctx, "보유자", holder_faction, 0, passive_skill_id="PassiveSkill")
        _add(ctx, "대상", target_faction, 2)
        _add(ctx, "다른 대상", target_faction, 1)
        return ctx, manager

    def test_target_two_columns_away_doubles_atk(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))
        assert _damage_taken(ctx, TARGET) == 5 + 5 + 3

    def test_adjacent_target_is_normal(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(HOLDER, "[공격/다른 대상]", ctx)
        )
        assert _damage_taken(ctx, OTHER) == 5 + 3

    def test_holder_move_before_attack_is_measured(self, monkeypatch):
        """같은 커맨드의 이동을 반영한 뒤의 거리로 잰다."""
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(
            parse_character_command(HOLDER, "[이동/2열 - 공격/대상]", ctx)
        )
        assert _damage_taken(ctx, TARGET) == 5 + 3

    def test_enemy_distance_measured_at_post(self, monkeypatch):
        """에너미는 정산(POST) 시점 위치로 잰다 — 대상이 다가오면 풀린다."""
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup(holder_faction=FactionType.ENEMY)
        manager.process_command(
            parse_character_command(HOLDER, "[공격/대상 - 공격/다른 대상]", ctx)
        )
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(parse_character_command(TARGET, "[이동/2열]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        assert _damage_taken(ctx, TARGET) == 5 + 3
        assert _damage_taken(ctx, OTHER) == 5 + 3

    def test_enemy_distant_target_doubles_at_post(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup(holder_faction=FactionType.ENEMY)
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        assert _damage_taken(ctx, TARGET) == 5 + 5 + 3

    def test_multi_column_target_uses_nearest_column(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx = _context(
            _buff_mod_passive(
                BuffAtk,
                value=5,
                value_type=ValueType.INTEGER,
                condition=TargetAtLeastDistanceCondition(value=2),
            )
        )
        manager = _manager(ctx)
        _add(ctx, "보유자", FactionType.ALLY, 0, passive_skill_id="PassiveSkill")
        # 2~3열을 차지 — 가장 가까운 열(2열)까지 거리 1.
        _add(ctx, "대상", FactionType.ENEMY, 1, span=2)
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))
        assert _damage_taken(ctx, TARGET) == 5 + 3


class TestAtkAgainstTargetThatDidNotMove:
    def _setup(self):
        ctx = _context(
            _buff_mod_passive(
                BuffAtk,
                value=5,
                value_type=ValueType.INTEGER,
                condition=TargetDidNotMoveThisTurnCondition(),
            )
        )
        manager = _manager(ctx)
        _add(ctx, "보유자", FactionType.ENEMY, 0, passive_skill_id="PassiveSkill")
        _add(ctx, "대상", FactionType.ALLY, 1)
        return ctx, manager

    def test_target_that_stayed_takes_doubled_atk(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        assert _damage_taken(ctx, TARGET) == 5 + 5 + 3

    def test_target_that_moved_during_ally_action_dodges_bonus(self, monkeypatch):
        monkeypatch.setattr("random.randint", lambda a, b: 3)
        ctx, manager = self._setup()
        manager.process_command(parse_character_command(HOLDER, "[공격/대상]", ctx))
        manager.to_phase(RoundPhaseType.ALLY_ACTION)
        manager.process_command(parse_character_command(TARGET, "[이동/1열]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        assert _damage_taken(ctx, TARGET) == 5 + 3
