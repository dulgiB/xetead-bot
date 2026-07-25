"""패시브(코모이디아) + 코스트 2 스킬(트라고디아) + 코스트 3 스킬(인형극)을 가진
캐릭터의 스킬셋 통합 테스트. 스프레드시트 행이 각 데이터클래스의 from_dict()를
거쳐 로드됐을 때 의도대로 동작하는지 확인한다.

이 캐릭터("메긴하아트_테스트")는 실제 캠페인 데이터가 아니라 테스트 전용으로
만들어진 캐릭터라 CLAUDE.md의 실제 캐릭터 고유명사 노출 금지 규칙이 적용되지
않는다(요청 시점부터 "_테스트" 접미사로 명시).

시나리오:
- 패시브(코모이디아): 자신에게 (패시브가 아닌) 버프가 부여되어 있을 때, 누군가
  사거리 내의 아군을 공격하면 공격자에게 공격 굴림 50%만큼 반격 대미지를
  입힌다. 맞은 아군이 자신이면 80%.
- 코스트 2(트라고디아): 대상에게 공격 굴림 230% 대미지 + 자신에게 2턴간
  [오데](주는 대미지 +20%) 부여.
- 코스트 3(인형극): 사거리 내에서 자신 외의 아군을 최대 2명 선택해 2턴간
  [네브로스파스톤](주는 대미지 +25%, 받는 대미지 +10%)으로 지정하고, 자신에게
  2턴간 [갈채](사거리 내 [네브로스파스톤] 아군이 공격할 때마다 자신도 그
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
        "오데": BuffData.from_dict(
            {
                "id": "오데",
                "buff_name": "BuffGivenDamage",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": 20,
                "value_type": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": "버프. 주는 대미지가 20% 증가한다.",
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "네브로스파스톤": BuffData.from_dict(
            {
                "id": "네브로스파스톤",
                "buff_name": "BuffGivenAndReceivedDamage",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": (
                    "버프. 주는 대미지가 25% 증가하는 대신 받는 대미지가 10% 증가한다."
                ),
                "is_debuff": False,
                "max_stack": "",
            }
        ),
        "갈채": BuffData.from_dict(
            {
                "id": "갈채",
                "buff_name": "BuffCounterDamageOnMarkedAllyAttack",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": (
                    "버프. 사거리 내의 [네브로스파스톤]으로 지정된 아군이 누군가를 "
                    "공격할 때마다 자신도 그 대상에게 공격 굴림 60% 대미지를 입힌다."
                ),
                "is_debuff": False,
                "max_stack": "",
                "reference_buff_id": "네브로스파스톤",
            }
        ),
        "받는대미지감소_테스트": BuffData.from_dict(
            {
                "id": "받는대미지감소_테스트",
                "buff_name": "BuffReceivedDamage",
                "duration_turn_value": 2,
                "duration_count_value": "",
                "duration_count_deduct_condition": "",
                "value": -50,
                "value_type": "퍼센트",
                "condition": "",
                "condition_value": "",
                "description": "테스트 전용. 받는 대미지가 50% 감소한다.",
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
                "value": "",
                "value_type": "",
                "condition": "",
                "condition_value": "",
                "description": "테스트 전용. 도발.",
                "is_debuff": True,
                "max_stack": "",
            }
        ),
    }


def _passive_buff_dict() -> dict[str, PassiveBuffData]:
    """'버프_패시브' 시트의 행(코모이디아의 버프 모디파이어 경로)."""
    return {
        "코모이디아": PassiveBuffData.from_dict(
            {
                "id": "코모이디아",
                "buff_name": "BuffCounterDamageOnAllyInRangeDamaged",
                "value": "",
                "value_type": "",
                "condition": "HolderHasBuffCondition",
                "condition_value": "",
                "description": "",
            }
        ),
    }


def _passive_skill_dict() -> dict[str, PassiveSkillData]:
    return {
        "코모이디아": PassiveSkillData.from_dict(
            {
                "id": "코모이디아",
                "trigger": "사거리 내 아군 피격 시",
                "target_type": "자신",
                "buff_id": "코모이디아",
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
        "트라고디아": SkillData.from_dict(
            {
                "id": "트라고디아",
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
                "buff_id_1": "오데",
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
                    "[오데]를 부여한다."
                ),
            }
        ),
        "인형극": SkillData.from_dict(
            {
                "id": "인형극",
                "target_rule": "SkillTargetRuleNamed",
                "target_count": 2,
                "cost": 3,
                "effect_0": "SkillEffectAddBuff",
                "condition_0": "",
                "condition_value_0": "",
                "value_source_0": "",
                "value_0": "",
                "value_type_0": "",
                "buff_id_0": "네브로스파스톤",
                "buff_stack_cap_0": "",
                "target_override_0": "",
                "effect_1": "SkillEffectAddBuff",
                "condition_1": "",
                "condition_value_1": "",
                "value_source_1": "",
                "value_1": "",
                "value_type_1": "",
                "buff_id_1": "갈채",
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
                    "[네브로스파스톤]으로 지정하고, 자신에게 2턴간 [갈채]를 부여한다."
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


class TestComoediaPassive:
    """패시브: 자신에게 버프가 부여되어 있을 때, 사거리 내 아군이 공격받으면
    공격자에게 반격한다. 맞은 아군이 자신이면 반격 비율이 더 높다."""

    def _add_holder_and_ally(self, ctx: BattlefieldContext, *, holder_range: int = 5):
        ctx.add_character(
            get_test_preset(
                "메긴하아트_테스트",
                atk=50,
                attack_range=holder_range,
                passive_skill_id="코모이디아",
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
        holder = CharacterId("메긴하아트_테스트")
        enemy = CharacterId("적군")
        # 조건 충족용으로 [오데](주는 대미지 수정자)가 아니라 [갈채](수치를
        # 건드리지 않는 반응형 버프)를 부여한다 — 이 테스트는 반격의 "기본
        # 비율"만 확인하고, 다른 버프와의 중첩은 별도 테스트에서 확인한다.
        ctx.buff_container.add(
            _buff_add(given_by="메긴하아트_테스트", applied_to="메긴하아트_테스트", buff_id="갈채")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(
            parse_character_command(enemy, "[공격/아군2]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        # 홀더 공격 굴림 50 × 50% = 25.
        assert enemy_hp_before - enemy_hp_after == 25

    def test_counters_at_higher_percent_when_holder_itself_is_hit(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        holder = CharacterId("메긴하아트_테스트")
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="메긴하아트_테스트", applied_to="메긴하아트_테스트", buff_id="갈채")
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
        """반격도 홀더가 실제로 가하는 대미지이므로, 홀더가 보유한 [오데](주는
        대미지 +20%)가 반격 수치에도 반영되어야 하고 계산식에도 드러나야
        한다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        holder = CharacterId("메긴하아트_테스트")
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="메긴하아트_테스트", applied_to="메긴하아트_테스트", buff_id="오데")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        before = len(ctx.results)
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp
        reply = format_battle_reply(ctx, enemy, ctx.results[before:])

        # 50 × 50%[코모이디아] × (1 + 0.2)[오데] = 30.
        assert enemy_hp_before - enemy_hp_after == 30
        assert "0.5[코모이디아: 메긴하아트_테스트]" in reply
        assert "0.2[오데]" in reply

    def test_counter_damage_respects_attackers_own_received_damage_buff(self):
        """반격 대미지도 공격자(반격 대상)가 평소 자신이 공격당할 때 받는
        "받는 대미지" 버프의 영향을 받아야 한다."""
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        holder = CharacterId("메긴하아트_테스트")
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="메긴하아트_테스트", applied_to="메긴하아트_테스트", buff_id="갈채")
        )
        ctx.buff_container.add(
            _buff_add(given_by="적군", applied_to="적군", buff_id="받는대미지감소_테스트")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[공격/아군2]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        # 50 × 50%[코모이디아] × (1 - 0.5)[받는대미지감소_테스트] = 12(내림).
        assert enemy_hp_before - enemy_hp_after == 12

    def test_no_counter_when_holder_has_no_buff(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx)
        enemy = CharacterId("적군")

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(
            parse_character_command(enemy, "[공격/아군2]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        assert enemy_hp_before == enemy_hp_after

    def test_no_counter_when_ally_out_of_holders_range(self):
        ctx = _make_context()
        manager = _setup_enemy_pre_phase(ctx)
        self._add_holder_and_ally(ctx, holder_range=1)
        enemy = CharacterId("적군")
        ctx.buff_container.add(
            _buff_add(given_by="메긴하아트_테스트", applied_to="메긴하아트_테스트", buff_id="오데")
        )

        enemy_hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(
            parse_character_command(enemy, "[공격/아군2]", ctx)
        )
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        enemy_hp_after = ctx.characters[enemy].status.curr_hp

        assert enemy_hp_before == enemy_hp_after


class TestTragodiaSkill:
    """코스트 2 스킬: 공격 굴림 230% 대미지 + 자신에게 2턴간 [오데] 부여."""

    def test_deals_damage_and_grants_ode_to_self(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("메긴하아트_테스트")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("메긴하아트_테스트", atk=100, skill_1_id="트라고디아"),
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
            parse_character_command(caster, "[트라고디아/적군]", ctx)
        )
        hp_after = ctx.characters[target].status.curr_hp

        assert hp_before - hp_after == 230
        buff = ctx.buff_container.get_buff(caster, "오데")
        assert buff is not None
        assert buff.duration.remaining_turns == 2


class TestInhyeongGeukSkill:
    """코스트 3 스킬: 사거리 내 자신 외 아군을 대상의 수만큼 선택해 2턴간
    [네브로스파스톤] 지정 + 자신에게 2턴간 [갈채] 부여."""

    def test_grants_nebrospaston_to_chosen_allies_and_galchae_to_self(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("메긴하아트_테스트")
        ally_a = CharacterId("아군A")
        ally_b = CharacterId("아군B")
        ctx.add_character(
            get_test_preset("메긴하아트_테스트", skill_1_id="인형극", attack_range=5),
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
            parse_character_command(caster, "[인형극/아군A/아군B]", ctx)
        )

        assert ctx.buff_container.get_buff(ally_a, "네브로스파스톤") is not None
        assert ctx.buff_container.get_buff(ally_b, "네브로스파스톤") is not None
        galchae = ctx.buff_container.get_buff(caster, "갈채")
        assert galchae is not None
        assert galchae.duration.remaining_turns == 2

    def test_can_target_fewer_than_the_maximum(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        caster = CharacterId("메긴하아트_테스트")
        ally_a = CharacterId("아군A")
        ctx.add_character(
            get_test_preset("메긴하아트_테스트", skill_1_id="인형극", attack_range=5),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("아군A"), FactionType.ALLY, BattlefieldColumnIndex(1)
        )

        manager.process_command(
            parse_character_command(caster, "[인형극/아군A]", ctx)
        )

        assert ctx.buff_container.get_buff(ally_a, "네브로스파스톤") is not None
        assert ctx.buff_container.get_buff(caster, "갈채") is not None


class TestNebrospastonBuff:
    """[네브로스파스톤]: 주는 대미지 +25%, 받는 대미지 +10%."""

    def test_increases_given_damage(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        marked = CharacterId("마크아군")
        target = CharacterId("적군")
        ctx.add_character(
            get_test_preset("마크아군", atk=100), FactionType.ALLY, BattlefieldColumnIndex(0)
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=1000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            _buff_add(given_by="마크아군", applied_to="마크아군", buff_id="네브로스파스톤")
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
            get_test_preset("적군", atk=100), FactionType.ENEMY, BattlefieldColumnIndex(0)
        )
        ctx.buff_container.add(
            _buff_add(given_by="마크아군", applied_to="마크아군", buff_id="네브로스파스톤")
        )

        hp_before = ctx.characters[marked].status.curr_hp
        manager.process_command(parse_character_command(enemy, "[공격/마크아군]", ctx))
        manager.to_phase(RoundPhaseType.ENEMY_POST_ACTION)
        hp_after = ctx.characters[marked].status.curr_hp

        assert hp_before - hp_after == 110


class TestGalchaeBuff:
    """[갈채]: 사거리 내의 [네브로스파스톤] 아군이 누군가를 공격할 때마다,
    자신도 그 대상에게 공격 굴림 60% 대미지를 입힌다."""

    def _setup(self):
        ctx = _make_context()
        manager = _setup_ally_phase(ctx)
        holder = CharacterId("메긴하아트_테스트")
        marked = CharacterId("마크아군")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset("메긴하아트_테스트", atk=100, attack_range=5),
            FactionType.ALLY,
            BattlefieldColumnIndex(0),
        )
        ctx.add_character(
            get_test_preset("마크아군", atk=100), FactionType.ALLY, BattlefieldColumnIndex(1)
        )
        ctx.add_character(
            get_test_preset("적군", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(1),
        )
        ctx.buff_container.add(
            _buff_add(given_by="메긴하아트_테스트", applied_to="메긴하아트_테스트", buff_id="갈채")
        )
        ctx.buff_container.add(
            _buff_add(given_by="메긴하아트_테스트", applied_to="마크아군", buff_id="네브로스파스톤")
        )
        return ctx, manager, holder, marked, enemy

    def test_holder_also_deals_damage_to_marked_allys_target(self):
        ctx, manager, holder, marked, enemy = self._setup()

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        # 마크아군의 공격(100 × 1.25[네브로스파스톤] = 125) + 홀더의 반응
        # 대미지(공격 굴림 100 × 60% = 60) = 185.
        assert hp_before - hp_after == 185

    def test_reply_labels_bonus_damage_with_holders_name(self):
        """갈채는 홀더 자신이 아니라 마크아군의 행동에 편승해 발동하므로,
        (도발처럼) 계산식에 "[갈채: 부여자]" 형태로 누구의 갈채인지 드러나야
        한다."""
        ctx, manager, holder, marked, enemy = self._setup()

        before = len(ctx.results)
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        reply = format_battle_reply(ctx, marked, ctx.results[before:])

        assert "0.6[갈채: 메긴하아트_테스트]" in reply

    def test_bonus_damage_respects_holders_own_given_damage_buff(self):
        """갈채의 추가 대미지도 홀더가 실제로 가하는 대미지이므로, 홀더가
        보유한 [오데](주는 대미지 +20%)가 반영되어야 한다."""
        ctx, manager, holder, marked, enemy = self._setup()
        ctx.buff_container.add(
            _buff_add(given_by="메긴하아트_테스트", applied_to="메긴하아트_테스트", buff_id="오데")
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        # 마크아군의 공격(125) + 홀더의 반응 대미지(100 × 0.6 × 1.2[오데] = 72) = 197.
        assert hp_before - hp_after == 197

    def test_bonus_damage_respects_targets_own_received_damage_buff(self):
        """갈채의 추가 대미지도 대상이 평소 자신이 공격당할 때 받는 "받는
        대미지" 버프의 영향을 받아야 한다."""
        ctx, manager, holder, marked, enemy = self._setup()
        ctx.buff_container.add(
            _buff_add(given_by="적군", applied_to="적군", buff_id="받는대미지감소_테스트")
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(marked, "[공격/적군]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        # 마크아군의 공격은 원래도 대상의 받는 대미지 감소 50%를 받는
        # 일반 공격이라 100 × 1.25[네브로스파스톤] × 0.5[받는대미지감소] = 62(내림).
        # 홀더의 반응 대미지도 동일하게 대상의 받는 대미지 감소가 적용되어
        # 100 × 0.6 × 0.5 = 30. 합계 92.
        assert hp_before - hp_after == 92

    def test_bonus_damage_ignores_holders_own_taunt_status(self):
        """갈채의 추가 대미지는 홀더가 스스로 선언한 공격이 아니라 마크아군의
        공격에 편승해 발동하는 반응형 대미지라, 홀더가 다른 적에게 도발당한
        상태여도 도발자가 아니라 마크아군이 실제로 공격한 대상에게 그대로
        꽂혀야 한다(도발의 대상 리다이렉트는 도발당한 캐릭터 본인이 선언한
        공격에만 적용되고, process() 시작 시 그 시점에 존재하는 항목만
        훑으므로 나중에 추가되는 갈채 반응 대미지는 애초에 리다이렉트 대상이
        아니다)."""
        ctx, manager, holder, marked, enemy = self._setup()
        taunter = CharacterId("도발한적")
        ctx.add_character(
            get_test_preset("도발한적", max_hp=10000),
            FactionType.ENEMY,
            BattlefieldColumnIndex(0),
        )
        ctx.buff_container.add(
            _buff_add(given_by="도발한적", applied_to="메긴하아트_테스트", buff_id="도발_테스트")
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
        holder = CharacterId("메긴하아트_테스트")
        unmarked = CharacterId("마크없는아군")
        enemy = CharacterId("적군")
        ctx.add_character(
            get_test_preset("메긴하아트_테스트", atk=100, attack_range=5),
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
            _buff_add(given_by="메긴하아트_테스트", applied_to="메긴하아트_테스트", buff_id="갈채")
        )

        hp_before = ctx.characters[enemy].status.curr_hp
        manager.process_command(parse_character_command(unmarked, "[공격/적군]", ctx))
        hp_after = ctx.characters[enemy].status.curr_hp

        assert hp_before - hp_after == 100
