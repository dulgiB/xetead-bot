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
    ActionType,
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
        # 방어막/반사 등이 대미지·회복 항목 자체를 제거(무효화)했을 때
        # (대상, 표시 메시지) 쌍을 기록한다. NoDataEvent/ReflectEvent가 채운다.
        self.nullified_effect_list: list[tuple[CharacterId, str]] = []
        # 이 effect(주로 이동)가 유발한 반응(예: ON_ENEMY_MOVE 반격)이 이미
        # 별도 계산기로 확정 처리된 뒤, 그 결과 로그만 이 effect의 로그에
        # 얹어 넣기 위한 목록. BuffContainer.on_enemy_move()가 채운다.
        self.extra_log_entries: list[BattleLogEntry] = []


class CommandPartCalculator:
    def __init__(self, data: CommandPartData, context: "BattlefieldContext"):
        self.context = context
        # "본인/아군이 대미지를 주었을 때"를 트리거로 쓰는 ON_ACTION 패시브가
        # ActionType.USE_ITEM(대미지를 주는 아이템 사용)까지 발동시키지 않도록
        # 구분하는 용도. CommandPartCalculator 인스턴스는 CommandPartData
        # 하나(=커맨드 파트 하나)당 1:1로 생성되므로 여기서 한 번만 읽으면 된다.
        self.action_type: Optional[ActionType] = (
            data.original_part.type_ if data.original_part is not None else None
        )
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
        # 스킬(GIVEN_DAMAGE/GIVEN_HEAL 기반)의 발동 여부 기록. 세 번째 원소는
        # 발동원 구분자로, 패시브 스킬 효과 인덱스(int)나 버프 모디파이어
        # 식별 문자열(str) 등 호출측이 각자 고유하게 정하는 값이다.
        self._fired_given_value_passives: set[tuple[int, CharacterId, int | str]] = (
            set()
        )

        # 스킬 하나(커맨드 파트 하나)가 effect를 여러 개 써서 같은 대상에게 여러 번
        # 대미지를 입혀도 실제로는 "한 번의 타격"이다. ON_ATTACK/ON_HIT count형
        # 버프(공격 시/피격 시 차감)가 effect마다 중복 발동하지 않도록, 이
        # CommandPartCalculator 인스턴스(=한 번의 process() 호출) 생애 동안
        # 공격자/대상별로 한 번만 발동시킨다. 인스턴스는 process() 호출마다
        # 새로 생성되므로(command_processors.py) 별도 리셋이 필요 없다.
        self._on_attack_fired: set[CharacterId] = set()
        self._on_hit_fired: set[CharacterId] = set()

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
        # 이 페이즈에서 실제로 대미지가 적용되는 effect만 대상으로 해야
        # 희생 방어 횟수 차감이 PRE/POST 이중 처리에서도 1회만 일어난다.
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
            self.context.buff_container.on_enemy_move(
                move_data.character_id, self, effect_seq_number
            )

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
            return (
                apply_timing is None or apply_timing == RoundPhaseType.ENEMY_POST_ACTION
            )
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
                    damage_calc.base.attacker_id,
                    original,
                    ignores_taunt=damage_calc.base.ignores_taunt,
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
        ignores_taunt: bool = False,
    ) -> tuple[CharacterId, float]:
        """도발(공격자 기준) → 희생 방어(대상 기준) 순으로 최종 대상을 결정한다.

        ignores_taunt=True(열 광역기 등)면 도발 리다이렉트 단계를 건너뛴다.

        반환: (최종 대상, 희생 방어 경감 퍼센트). 희생 방어가 없으면 경감은 0.
        """
        final = original_target
        reduction: float = 0
        # 도발: 공격자가 도발 상태면 도발자를 노린다. 단, 열 광역기 등
        # ignores_taunt 항목은 대상별 개별 판단이 설계 의도이므로 건너뛴다.
        if not ignores_taunt:
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

        # 공격자 측 ON_ATTACK 버프, 대상 측 ON_HIT 버프는 같은 스킬(커맨드 파트)
        # 안에서 effect가 여러 개라도, 그리고 하나의 effect가 광역이라도 행동
        # 1회당(공격자/대상 조합이 아니라 공격자 1명/대상 1명당) 한 번만
        # 적용/차감한다 — 여러 effect가 같은 대상에게 대미지를 더하는 것은 여러 번의
        # 타격이 아니라 한 번의 타격을 구성하는 요소들이기 때문이다. 이 dedup은
        # 인스턴스 전체(=이 커맨드 파트의 process() 호출 전체)에 걸쳐 유지된다
        # (self._on_attack_fired/_on_hit_fired, __init__ 참고).
        for damage_calc in live_damage_calcs:
            attacker_id = damage_calc.base.attacker_id
            if attacker_id in self._on_attack_fired:
                continue
            self._on_attack_fired.add(attacker_id)
            self._apply_buff_events(
                effect_seq_number,
                attacker_id,
                BuffCountDeductCondition.ON_ATTACK,
                damage_calc.base.target_id,
            )

        for damage_calc in live_damage_calcs:
            target_id = damage_calc.base.target_id
            if target_id not in self._on_hit_fired:
                self._on_hit_fired.add(target_id)
                self._apply_buff_events(
                    effect_seq_number,
                    target_id,
                    BuffCountDeductCondition.ON_HIT,  # noqa: F821
                    damage_calc.base.attacker_id,
                )
            self.context.buff_container.on_character_damaged(
                damage_calc.base.target_id, self, effect_seq_number
            )
            self.context.buff_container.on_ally_in_range_damaged(
                damage_calc.base.target_id,
                damage_calc.base.attacker_id,
                self,
                effect_seq_number,
            )
            self.context.buff_container.on_ally_in_range_attacked(
                damage_calc.base.attacker_id,
                damage_calc.base.target_id,
                self,
                effect_seq_number,
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
            # roll_display가 이미 설정돼 있으면 덮어쓰지 않는다 — 반사(BuffReflect)처럼
            # 이 damage_calc 자체가 FIXED 고정값이라 여기서 다시 계산하면 표시할 게
            # 없어지는(None) 대신, 이벤트가 미리 만들어 둔 계산식 문자열을 그대로 쓴다.
            if damage_calc.roll_display is None:
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
        if data.gate_value_source == ValueSourceType.GIVEN_HEAL:
            total = sum(
                d.result_value
                for effect in self.data_by_effect[: effect_seq_number + 1]
                for d in effect.heal_data_list
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


def _damage_calcs_for_target(
    calculator: "CommandPartCalculator", target_id: CharacterId
) -> list["DamageCalculateData"]:
    return [
        damage_calc
        for effect_data in calculator.data_by_effect
        for damage_calc in effect_data.damage_data_list
        if damage_calc.result_value is not None
        and damage_calc.base.target_id == target_id
    ]


def _build_damage_entry(
    calculator: "CommandPartCalculator", target_id: CharacterId
) -> BattleLogEntry:
    """target_id에게 이 커맨드 파트(스킬 1회 사용) 안에서 일어난 대미지를 전부 모아
    하나의 로그 엔트리로 합친다. 스킬 하나가 effect를 여러 개 써서 같은 대상에게
    여러 번 대미지를 입혀도(예: 공격 굴림 대미지 + 스택 소모 대미지) 실제로는
    한 번의 타격이므로, HP도 순차적으로 두 줄 보여주지 않고 최종 결과 한 줄로
    보여준다. 계산식은 각 구성 요소의 계산식을 "+"로 이어붙인다(구성 요소가
    하나뿐이면 그 계산식을 그대로 써서 기존 표시와 동일하게 유지한다)."""
    calcs = _damage_calcs_for_target(calculator, target_id)
    total_value = sum(c.result_value for c in calcs if c.result_value is not None)
    last = calcs[-1]
    if len(calcs) == 1:
        roll_display = last.roll_display
    else:
        roll_display = " + ".join(
            c.roll_display if c.roll_display is not None else str(c.result_value)
            for c in calcs
        )
    return BattleLogEntry(
        target_name=target_id.name,
        kind=BattleLogEntryKind.DAMAGE,
        result=f"대미지 {total_value}",
        roll_display=roll_display,
        value=total_value,
        hp_after=last.hp_after,
        max_hp=last.max_hp,
    )


def build_buff_add_log_entry(
    context: "BattlefieldContext", buff_add: "BuffAddData"
) -> BattleLogEntry:
    """buff_container.add()로 이미 반영된 BuffAddData 하나를 로그 엔트리로
    변환한다. build_log_entries()의 일반 경로와, ON_ACTION 버프 이벤트가
    (calculator.data_by_effect[...].buff_add_data_list를 거치지 않고) 직접
    buff_container.add()를 호출한 뒤 extra_log_entries에 결과를 얹는 경로
    양쪽에서 재사용한다 — 후자는 트리거된 시점의 페이즈(PRE/POST)에 따라
    _process_buff_add()가 항상 호출되지 않을 수 있어, 일반 경로로는 로그를
    보장할 수 없기 때문이다."""
    buff = context.get_buff_instance(buff_add.applied_to, buff_add.buff_id)
    label = buff.display_id_label() if buff is not None else buff_add.buff_id
    if buff is not None and buff.max_stack:
        result = f"[{label}]×{buff_add.stack_value} 부여 → 최종 {buff.stack_count}"
    else:
        duration_text = buff.duration.display_text() if buff is not None else ""
        result = f"[{label}] 부여{duration_text}"
    return BattleLogEntry(
        target_name=buff_add.applied_to.name,
        kind=BattleLogEntryKind.BUFF_ADD,
        result=result,
        buff_id=buff_add.buff_id,
        stack_delta=buff_add.stack_value,
    )


def build_log_entries(calculator: "CommandPartCalculator") -> list[BattleLogEntry]:
    """process() 완료 후 calculator.data_by_effect를 순회해 대상별 로그 엔트리를 만든다.

    로그_전투 시트에 대상 1명당 1행으로 기록하는 것과, 봇 답글 포매터
    (app/bot/battle_reply_text.py)가 플레이어에게 보여줄 텍스트를 조립하는 것
    양쪽에 쓰인다.
    """
    entries: list[BattleLogEntry] = []
    context = calculator.context

    # 대상별로 대미지를 입힌 마지막 effect 인덱스를 미리 계산해 둔다 — 같은
    # 대상에게 여러 effect가 대미지를 입히면 마지막 effect 위치에서 한 번만
    # 합쳐서 내보내기 위함(_build_damage_entry 참고).
    last_damage_effect_index: dict[CharacterId, int] = {}
    for idx, effect_data in enumerate(calculator.data_by_effect):
        for damage_calc in effect_data.damage_data_list:
            if damage_calc.result_value is not None:
                last_damage_effect_index[damage_calc.base.target_id] = idx

    emitted_damage_targets: set[CharacterId] = set()
    for idx, effect_data in enumerate(calculator.data_by_effect):
        # 같은 effect 안에서 스택 변화(소모/부여)와 수치 변화(대미지/회복)가
        # 함께 일어나는 경우(SkillEffectConsumeStackForDamage,
        # SkillEffectHealAndFillBuffStack) 스택 변화를 먼저 보여준다 —
        # 실제 계산도 스택 소모/부여 결과를 대미지/회복 값이 참조하는 순서다.
        for remove_calc in effect_data.buff_remove_data_list:
            if not remove_calc.result_value:
                continue
            final_stack = context.get_buff_stack(
                remove_calc.base.applied_to, remove_calc.base.buff_id
            )
            entries.append(
                BattleLogEntry(
                    target_name=remove_calc.base.applied_to.name,
                    kind=BattleLogEntryKind.BUFF_REMOVE,
                    result=(
                        f"[{remove_calc.base.buff_id}]×{remove_calc.result_value} 소모"
                        f" → 최종 {final_stack}"
                    ),
                    buff_id=remove_calc.base.buff_id,
                    stack_delta=remove_calc.result_value,
                )
            )
        for buff_add in effect_data.buff_add_data_list:
            # _process_buff_add()와 동일한 게이트를 다시 통과시킨다 — 그러지
            # 않으면 조건부 버프(예: ConsumedBuffStackCountCondition)가 게이트에
            # 막혀 실제로는 부여되지 않았는데도 "[버프] 부여" 로그가 남는다.
            if not calculator._buff_add_gate_passes(buff_add, idx):
                continue
            entries.append(build_buff_add_log_entry(context, buff_add))
        for target_id, message in effect_data.nullified_effect_list:
            entries.append(
                BattleLogEntry(
                    target_name=target_id.name,
                    kind=BattleLogEntryKind.NO_EFFECT,
                    result=message,
                )
            )
        # result_value가 None이면 이번 페이즈에서 아직 적용되지 않았거나(예: PRE 단계의
        # POST용 대미지/힐) 대상이 이미 사망해 건너뛴 항목이므로 로그에 남기지 않는다.
        # 같은 대상에게 이 파트의 다른(뒤쪽) effect가 아직 대미지를 더 줄 예정이면
        # 여기서는 내보내지 않고, 마지막으로 대미지를 준 effect 위치에서 합쳐서 낸다.
        for damage_calc in effect_data.damage_data_list:
            if damage_calc.result_value is None:
                continue
            target_id = damage_calc.base.target_id
            if target_id in emitted_damage_targets:
                continue
            if last_damage_effect_index.get(target_id) != idx:
                continue
            emitted_damage_targets.add(target_id)
            entries.append(_build_damage_entry(calculator, target_id))
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
        entries.extend(effect_data.extra_log_entries)
    return entries
