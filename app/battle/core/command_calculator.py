from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import (
    BattleLogEntry,
    BattleLogEntryKind,
    BuffRemoveCalculateData,
    CommandPartData,
    DamageCalculateData,
    HealCalculateData,
)
from battle.objects.buff.buff_base import BuffAddData, BuffBase, BuffRemoveData
from battle.objects.character.buffed_stats import BuffedStats
from battle.objects.define import (
    BuffApplyTiming,
    BuffCountDeductCondition,
    CombatStatType,
    ValueSourceType,
)
from battle.objects.models import (
    CharacterId,
    DamageData,
    FloatValueModifier,
    HealData,
    MoveData,
    ValueWithModifiers,
)

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext


@dataclass
class CalculatorMutableData:
    def __init__(
        self,
        move_list: list[MoveData],
        damage_list: list[DamageData],
        heal_list: list[HealData],
        buff_add_list: list[BuffAddData],
        buff_remove_list: Optional[list[BuffRemoveData]] = None,
        apply_timing: Optional[RoundPhaseType] = None,
        debuff_clear_list: Optional[list[CharacterId]] = None,
    ):
        self.move_list: list[MoveData] = move_list
        self.damage_data_list: list[DamageCalculateData] = [
            DamageCalculateData(damage_data) for damage_data in damage_list
        ]
        self.heal_data_list: list[HealCalculateData] = [
            HealCalculateData(heal_data) for heal_data in heal_list
        ]
        self.buff_add_data_list: list[BuffAddData] = buff_add_list
        self.buff_remove_data_list: list[BuffRemoveCalculateData] = [
            BuffRemoveCalculateData(remove_data, None)
            for remove_data in (buff_remove_list or [])
        ]
        self.apply_timing: Optional[RoundPhaseType] = apply_timing
        self.debuff_clear_list: list[CharacterId] = debuff_clear_list or []


class CommandPartCalculator:
    def __init__(self, data: CommandPartData, context: "BattlefieldContext"):
        self.context = context
        self.buffed_stats_by_character: dict[CharacterId, BuffedStats] = {
            char_id: BuffedStats(
                character.status, {stat: [] for stat in CombatStatType}
            )
            for char_id, character in context.characters.items()
        }

        self.data_by_effect: list[CalculatorMutableData] = [
            CalculatorMutableData(
                data_per_effect.move_list,
                data_per_effect.damage_list,
                data_per_effect.heal_list,
                data_per_effect.buff_add_list,
                data_per_effect.buff_remove_list,
                data_per_effect.apply_timing,
                data_per_effect.debuff_clear_list,
            )
            for data_per_effect in data.data_per_effect
            if data_per_effect is not None
        ]

        # 대미지 리다이렉트(도발/희생 방어) 결과. {원래 대상: 치환 대상}
        # 같은 커맨드(스킬)의 buff_add 등 부가 효과도 이 매핑을 따라 함께 이동한다.
        self._redirect_map: dict[CharacterId, CharacterId] = {}

        # (effect_seq_number, holder) 조합당 1회만 발동해야 하는 패시브
        # 스킬(GIVEN_DAMAGE/GIVEN_HEAL 기반)의 발동 여부 기록.
        self._fired_given_value_passives: set[tuple[int, CharacterId, int]] = set()

    @classmethod
    def create_empty_for_buff(
        cls, context: "BattlefieldContext"
    ) -> "CommandPartCalculator":
        empty = cls(
            CommandPartData(
                original_part=None,
                data_per_effect=tuple(),
            ),
            context,
        )
        empty.data_by_effect.append(CalculatorMutableData([], [], [], []))
        return empty

    def process(
        self,
        phase: Optional[RoundPhaseType],
    ):
        # 대미지 처리 전에 리다이렉트 매핑을 먼저 계산한다.
        # (이 페이즈에서 실제로 대미지가 적용되는 effect만 대상으로 하여 1회만 차감)
        self._prepare_redirects(phase)

        if phase == RoundPhaseType.ENEMY_PRE_ACTION:
            for i in range(len(self.data_by_effect)):
                timing = self.data_by_effect[i].apply_timing
                if timing is None:
                    # 아군 스킬 동작: 이동과 PRE 타이밍 버프만 처리
                    self._process_move(i)
                    self._process_buff_add(i, phase)
                elif timing == RoundPhaseType.ENEMY_PRE_ACTION:
                    # 에너미 스킬 PRE effect: 전체 처리
                    self._process_move(i)
                    self._process_buff_remove(i)
                    self._process_damage(i)
                    self._process_heal(i)
                    self._process_all_buff_add(i)
                # ENEMY_POST_ACTION effect는 이 페이즈에서 처리하지 않음

        elif phase == RoundPhaseType.ALLY_ACTION:
            for i in range(len(self.data_by_effect)):
                self._process_move(i)
                self._process_buff_remove(i)
                self._process_damage(i)
                self._process_heal(i)
                self._process_buff_add(i, phase)

        elif phase == RoundPhaseType.ENEMY_POST_ACTION:
            for i in range(len(self.data_by_effect)):
                timing = self.data_by_effect[i].apply_timing
                if timing is None:
                    # 아군 스킬 동작: 대미지/힐과 POST 타이밍 버프만 처리 (이동은 PRE에서 완료)
                    self._process_buff_remove(i)
                    self._process_damage(i)
                    self._process_heal(i)
                    self._process_buff_add(i, phase)
                elif timing == RoundPhaseType.ENEMY_POST_ACTION:
                    # 에너미 스킬 POST effect: 전체 처리
                    self._process_move(i)
                    self._process_buff_remove(i)
                    self._process_damage(i)
                    self._process_heal(i)
                    self._process_all_buff_add(i)
                # ENEMY_PRE_ACTION effect는 이미 PRE에서 처리했으므로 건너뜀

        elif phase == RoundPhaseType.BUFF_UPDATE_AND_NEXT_ROUND_STANDBY:
            pass

        else:
            # phase가 없다면 BuffContainer에서 호출한 경우
            for i in range(len(self.data_by_effect)):
                self._process_move(i)
                self._process_buff_remove(i)
                self._process_damage(i)
                self._process_heal(i)

    def _process_move(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        for move_data in self.data_by_effect[effect_seq_number].move_list:
            self.context.move_character_to(
                move_data.character_id, move_data.to_position
            )
            if not move_data.is_forced:
                self.context.buff_container.on_voluntary_move(move_data.character_id)

    def _process_buff_remove(
        self: "CommandPartCalculator", effect_seq_number: int
    ) -> None:
        """적층형 버프의 스택을 실제로 차감하고, 실제 차감량을 result_value에
        기록한다(CONSUMED_BUFF_STACK 조회용). 스택이 부족해도 있는 만큼만 차감하고
        실패하지 않는다."""
        for remove_calc in self.data_by_effect[effect_seq_number].buff_remove_data_list:
            base = remove_calc.base
            buff = self.context.get_buff_instance(base.applied_to, base.buff_id)
            current = buff.stack_count if buff is not None else 0
            removed = min(base.requested_amount, current)
            if buff is not None and removed:
                buff.stack_count -= removed
            remove_calc.result_value = removed

    @staticmethod
    def _damage_processed_in_phase(
        apply_timing: Optional[RoundPhaseType], phase: Optional[RoundPhaseType]
    ) -> bool:
        """주어진 effect의 대미지가 해당 phase에서 실제로 적용되는지 여부.

        process()의 페이즈별 분기 로직과 일치해야 한다.
        """
        if phase == RoundPhaseType.ENEMY_PRE_ACTION:
            return apply_timing == RoundPhaseType.ENEMY_PRE_ACTION
        if phase == RoundPhaseType.ENEMY_POST_ACTION:
            return apply_timing is None or apply_timing == RoundPhaseType.ENEMY_POST_ACTION
        if phase == RoundPhaseType.ALLY_ACTION or phase is None:
            return True
        return False  # BUFF_UPDATE_AND_NEXT_ROUND_STANDBY 등

    def _prepare_redirects(
        self: "CommandPartCalculator", phase: Optional[RoundPhaseType]
    ) -> None:
        """도발/희생 방어 리다이렉트를 계산해 대미지 target을 치환하고 매핑을 기록한다.

        이 페이즈에서 실제로 대미지가 적용되는 effect만 대상으로 하므로, 희생 방어
        횟수 차감은 적군 커맨드의 PRE/POST 이중 처리에서도 한 번만 일어난다.
        기록된 매핑은 같은 커맨드의 buff_add(디버프 등) 부가 효과에도 적용된다.
        """
        self._redirect_map = {}
        for mutable in self.data_by_effect:
            if not self._damage_processed_in_phase(mutable.apply_timing, phase):
                continue
            for damage_calc in mutable.damage_data_list:
                original = damage_calc.base.target_id
                final, reduction = self._resolve_redirect(
                    damage_calc.base.attacker_id, original
                )
                if final != original:
                    damage_calc.base = replace(damage_calc.base, target_id=final)
                    self._redirect_map[original] = final
                # 희생 방어 경감: 보호자가 받는 대미지를 reduction%만큼 감소시킨다.
                # 버프가 아니라 게임 메커니즘이므로 FIXED 대미지에도 적용된다.
                if reduction:
                    damage_calc.received_modifiers.append(
                        FloatValueModifier(
                            source_name="희생 방어",
                            value=-reduction,
                            applies_to_fixed=True,
                        )
                    )

    def _resolve_redirect(
        self: "CommandPartCalculator",
        attacker_id: CharacterId,
        original_target: CharacterId,
    ) -> tuple[CharacterId, float]:
        """도발(공격자 기준) → 희생 방어(대상 기준) 순으로 최종 대상을 결정한다.

        반환: (최종 대상, 희생 방어 경감 퍼센트). 희생 방어가 없으면 경감은 0.
        """
        final = original_target
        reduction: float = 0
        # 도발: 공격자가 도발 상태면 도발자를 노린다.
        taunt_target = self._get_target_override(attacker_id)
        if taunt_target is not None and taunt_target in self.context.characters:
            final = taunt_target
        # 희생 방어: 현재 대상이 보호 중이면 보호자가 대신 맞는다.
        sacrifice = self._consume_sacrifice_protector(final)
        if sacrifice is not None:
            final, reduction = sacrifice
        return final, reduction

    def _get_target_override(
        self: "CommandPartCalculator", attacker_id: CharacterId
    ) -> Optional[CharacterId]:
        for buff in self.context.buff_container.get_buffs_by(
            attacker_id, BuffApplyTiming.ON_ACTION
        ):
            override = buff.get_target_override()
            if override is not None:
                return override
        return None

    def _redirect_applied_to(
        self: "CommandPartCalculator", data: BuffAddData
    ) -> BuffAddData:
        """buff_add의 부여 대상이 리다이렉트된 대미지 대상이면 함께 치환한다."""
        if data.applied_to in self._redirect_map:
            return replace(data, applied_to=self._redirect_map[data.applied_to])
        return data

    def _consume_sacrifice_protector(
        self: "CommandPartCalculator", target_id: CharacterId
    ) -> Optional[tuple[CharacterId, float]]:
        """target_id를 보호하는 희생 방어 버프가 있으면 (보호자, 경감 퍼센트)를 반환한다.

        경감 퍼센트는 버프의 value(퍼센트 포인트, 예: 20 → 보호자 받는 대미지 −20%)다.
        """
        for buff in self.context.buff_container.get_buffs_by(
            target_id, BuffApplyTiming.ON_ACTION
        ):
            protector = buff.get_sacrifice_override()
            if protector is None:
                continue
            if protector not in self.context.characters:
                continue  # 보호자가 전장에 없으면 무효
            if buff.duration.remaining_count is not None:
                buff.duration.remaining_count -= 1
                if buff.duration.finished:
                    self.context.buff_container.remove(buff.uid)
            return protector, buff.value
        return None

    @staticmethod
    def _is_live_damage_calc(
        context: "BattlefieldContext", damage_calc: "DamageCalculateData"
    ) -> bool:
        return (
            damage_calc.base.attacker_id in context.characters
            and damage_calc.base.target_id in context.characters
        )

    def _process_damage(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        # 대상 치환(도발/희생 방어)은 process() 시작 시 _prepare_redirects에서 일괄 수행됨.
        # 리다이렉트로도 구제되지 않은, 이미 사망한 공격자/대상에 대한 항목은 건너뛴다.
        # apply()가 무효화(BuffNoDamage 등)로 리스트 자체를 변경할 수 있으므로
        # 두 번째 순회는 최신 리스트를 다시 읽는다.
        live_damage_calcs = [
            damage_calc
            for damage_calc in self.data_by_effect[effect_seq_number].damage_data_list
            if self._is_live_damage_calc(self.context, damage_calc)
        ]

        # 공격자 측 ON_ATTACK 버프는 광역 효과라도 행동(effect) 1회당 한 번만
        # 적용/차감한다. GivenDamageModEvent 등은 자신이 attacker의 모든 대미지
        # 항목을 내부에서 순회하므로, 여러 번 호출하면 대상 수만큼 중복 적용된다.
        seen_attackers: set[CharacterId] = set()
        for damage_calc in live_damage_calcs:
            attacker_id = damage_calc.base.attacker_id
            if attacker_id in seen_attackers:
                continue
            seen_attackers.add(attacker_id)
            self._apply_buff_events(
                effect_seq_number,
                attacker_id,
                BuffCountDeductCondition.ON_ATTACK,
                damage_calc.base.target_id,
            )

        for damage_calc in live_damage_calcs:
            self._apply_buff_events(
                effect_seq_number,
                damage_calc.base.target_id,
                BuffCountDeductCondition.ON_HIT,  # noqa: F821
                damage_calc.base.attacker_id,
            )
            self.context.buff_container.on_character_damaged(
                damage_calc.base.target_id, self, effect_seq_number
            )
        for damage_calc in list(
            self.data_by_effect[effect_seq_number].damage_data_list
        ):
            if not self._is_live_damage_calc(self.context, damage_calc):
                continue
            attacker = self.context.characters[damage_calc.base.attacker_id]
            target = self.context.characters[damage_calc.base.target_id]

            is_magic_attack = (
                damage_calc.base.is_magic_attack
                if damage_calc.base.is_magic_attack is not None
                else attacker.status.is_magic_attacker
            )
            if is_magic_attack:
                damage_calc.received_modifiers.append(target.status.m_res)

            damage_value = ValueWithModifiers(
                damage_calc.base.value,
                damage_calc.given_modifiers,
                damage_calc.received_modifiers,
            )
            damage_calc.result_value = self.context.apply_damage(
                damage_calc.base.attacker_id,
                damage_calc.base.target_id,
                damage_value,
                self,
                effect_seq_number,
            )
            damage_calc.roll_display = damage_value.format_calculation()
            damage_calc.hp_after = target.status.curr_hp
            damage_calc.max_hp = target.status[CombatStatType.MAX_HP]

    @staticmethod
    def _is_live_heal_calc(
        context: "BattlefieldContext", heal_calc: "HealCalculateData"
    ) -> bool:
        return (
            heal_calc.base.healer_id in context.characters
            and heal_calc.base.target_id in context.characters
        )

    def _process_heal(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        # 이미 사망한 시전자/대상에 대한 항목은 건너뛴다. apply()가 무효화(BuffNoHeal 등)로
        # 리스트 자체를 변경할 수 있으므로 두 번째 순회는 최신 리스트를 다시 읽는다.
        for heal_calc in [
            heal_calc
            for heal_calc in self.data_by_effect[effect_seq_number].heal_data_list
            if self._is_live_heal_calc(self.context, heal_calc)
        ]:
            self._apply_buff_events(
                effect_seq_number,
                heal_calc.base.healer_id,
                None,
                heal_calc.base.target_id,
            )
            self._apply_buff_events(
                effect_seq_number,
                heal_calc.base.target_id,
                None,
                heal_calc.base.healer_id,
            )
        for heal_calc in list(self.data_by_effect[effect_seq_number].heal_data_list):
            if not self._is_live_heal_calc(self.context, heal_calc):
                continue
            target = self.context.characters[heal_calc.base.target_id]
            heal_value = ValueWithModifiers(
                heal_calc.base.value, heal_calc.given_modifiers, []
            )
            heal_calc.result_value = self.context.apply_heal(
                heal_calc.base.healer_id,
                heal_calc.base.target_id,
                heal_value,
                self,
                effect_seq_number,
            )
            heal_calc.roll_display = heal_value.format_calculation()
            heal_calc.hp_after = target.status.curr_hp
            heal_calc.max_hp = target.status[CombatStatType.MAX_HP]

    def _buff_add_gate_passes(
        self: "CommandPartCalculator", data: BuffAddData, effect_seq_number: int
    ) -> bool:
        """조건부 부여 게이트 판정. gate_value_source가 없으면 항상 통과."""
        if data.gate_value_source is None:
            return True
        if data.gate_value_source == ValueSourceType.CONSUMED_BUFF_STACK:
            total = sum(
                d.result_value
                for effect in self.data_by_effect[: effect_seq_number + 1]
                for d in effect.buff_remove_data_list
                if d.result_value is not None
            )
            return total >= (data.gate_value or 0)
        return True

    def _process_buff_add(
        self: "CommandPartCalculator",
        effect_seq_number: int,
        phase: RoundPhaseType,
    ) -> None:
        buff_add_list = self.data_by_effect[effect_seq_number].buff_add_data_list
        if phase == RoundPhaseType.ALLY_ACTION:
            for data in buff_add_list:
                if self._buff_add_gate_passes(data, effect_seq_number):
                    self.context.buff_container.add(self._redirect_applied_to(data))
        elif phase == RoundPhaseType.ENEMY_PRE_ACTION:
            for data in buff_add_list:
                if data.add_timing == RoundPhaseType.ENEMY_PRE_ACTION and (
                    self._buff_add_gate_passes(data, effect_seq_number)
                ):
                    self.context.buff_container.add(self._redirect_applied_to(data))
        elif phase == RoundPhaseType.ENEMY_POST_ACTION:
            for data in buff_add_list:
                if data.add_timing == RoundPhaseType.ENEMY_POST_ACTION and (
                    self._buff_add_gate_passes(data, effect_seq_number)
                ):
                    self.context.buff_container.add(self._redirect_applied_to(data))
        else:
            raise ValueError(f"Cannot add buffs at this phase: {phase}")

    def _process_all_buff_add(
        self: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        """apply_timing이 명시된 에너미 스킬 effect용: buff_add_timing에 무관하게 모두 추가."""
        for data in self.data_by_effect[effect_seq_number].buff_add_data_list:
            if self._buff_add_gate_passes(data, effect_seq_number):
                self.context.buff_container.add(self._redirect_applied_to(data))

    def _apply_buff_events(
        self: "CommandPartCalculator",
        effect_seq_number: int,
        char_id: CharacterId,
        deduct_condition: Optional[BuffCountDeductCondition],
        attacker_or_target: Optional[CharacterId] = None,
    ) -> None:
        buffs = self.context.buff_container.get_buffs_by(
            char_id, BuffApplyTiming.ON_ACTION
        )
        buff_events = [(buff, buff.create_event()) for buff in buffs]
        buff_events.sort(key=lambda pair: pair[1].priority.value)

        # 조건이 실제로 충족되어 발동한 버프만 지속 횟수를 소모한다.
        applied_buffs: list[BuffBase] = []
        for buff, event in buff_events:
            if event.is_applied(self.context, char_id, attacker_or_target):
                event.apply(char_id, attacker_or_target, self, effect_seq_number)
                applied_buffs.append(buff)

        if deduct_condition is not None:
            for buff in applied_buffs:
                buff.duration.deduct_count(deduct_condition)
                if buff.duration.finished:
                    self.context.buff_container.remove(buff.uid)


def build_log_entries(calculator: "CommandPartCalculator") -> list[BattleLogEntry]:
    """process() 완료 후 calculator.data_by_effect를 순회해 대상별 로그 엔트리를 만든다.

    로그_전투 시트에 대상 1명당 1행으로 기록하는 것과, 봇 답글 포매터
    (app/bot/battle_reply_text.py)가 플레이어에게 보여줄 텍스트를 조립하는 것
    양쪽에 쓰인다.
    """
    entries: list[BattleLogEntry] = []
    context = calculator.context
    for effect_data in calculator.data_by_effect:
        # 같은 effect 안에서 스택 변화(소모/부여)와 수치 변화(대미지/회복)가
        # 함께 일어나는 경우(SkillEffectConsumeStackForDamage,
        # SkillEffectHealAndFillBuffStack) 스택 변화를 먼저 보여준다 —
        # 실제 계산도 스택 소모/부여 결과를 대미지/회복 값이 참조하는 순서다.
        for remove_calc in effect_data.buff_remove_data_list:
            if not remove_calc.result_value:
                continue
            remaining = context.get_buff_stack(
                remove_calc.base.applied_to, remove_calc.base.buff_id
            )
            entries.append(
                BattleLogEntry(
                    target_name=remove_calc.base.applied_to.name,
                    kind=BattleLogEntryKind.BUFF_REMOVE,
                    result=(
                        f"[{remove_calc.base.buff_id}]×{remove_calc.result_value} 소모"
                        f" (잔여 {remaining})"
                    ),
                    buff_id=remove_calc.base.buff_id,
                    stack_delta=remove_calc.result_value,
                )
            )
        for buff_add in effect_data.buff_add_data_list:
            buff = context.get_buff_instance(buff_add.applied_to, buff_add.buff_id)
            if buff is not None and buff.max_stack:
                result = (
                    f"[{buff_add.buff_id}]×{buff_add.stack_value} 부여"
                    f" (잔여 {buff.stack_count})"
                )
            else:
                duration_text = buff.duration.display_text() if buff is not None else ""
                result = f"[{buff_add.buff_id}] 부여{duration_text}"
            entries.append(
                BattleLogEntry(
                    target_name=buff_add.applied_to.name,
                    kind=BattleLogEntryKind.BUFF_ADD,
                    result=result,
                    buff_id=buff_add.buff_id,
                    stack_delta=buff_add.stack_value,
                )
            )
        # result_value가 None이면 이번 페이즈에서 아직 적용되지 않았거나(예: PRE 단계의
        # POST용 대미지/힐) 대상이 이미 사망해 건너뛴 항목이므로 로그에 남기지 않는다.
        for damage_calc in effect_data.damage_data_list:
            if damage_calc.result_value is None:
                continue
            entries.append(
                BattleLogEntry(
                    target_name=damage_calc.base.target_id.name,
                    kind=BattleLogEntryKind.DAMAGE,
                    result=f"대미지 {damage_calc.result_value}",
                    roll_display=damage_calc.roll_display,
                    value=damage_calc.result_value,
                    hp_after=damage_calc.hp_after,
                    max_hp=damage_calc.max_hp,
                )
            )
        for heal_calc in effect_data.heal_data_list:
            if heal_calc.result_value is None:
                continue
            entries.append(
                BattleLogEntry(
                    target_name=heal_calc.base.target_id.name,
                    kind=BattleLogEntryKind.HEAL,
                    result=f"회복 {heal_calc.result_value}",
                    roll_display=heal_calc.roll_display,
                    value=heal_calc.result_value,
                    hp_after=heal_calc.hp_after,
                    max_hp=heal_calc.max_hp,
                )
            )
        for move_data in effect_data.move_list:
            entries.append(
                BattleLogEntry(
                    target_name=move_data.character_id.name,
                    kind=BattleLogEntryKind.MOVE,
                    result=f"{move_data.to_position}열로 이동",
                )
            )
        for target_id in effect_data.debuff_clear_list:
            entries.append(
                BattleLogEntry(
                    target_name=target_id.name,
                    kind=BattleLogEntryKind.DEBUFF_CLEAR,
                    result="모든 디버프 제거",
                )
            )
    return entries
