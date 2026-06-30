from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Optional

from battle.core.commands.define import RoundPhaseType
from battle.core.commands.models import (
    CommandPartData,
    DamageCalculateData,
    HealCalculateData,
)
from battle.objects.buff.buff_base import BuffAddData
from battle.objects.character.buffed_stats import BuffedStats
from battle.objects.define import (
    BuffApplyTiming,
    BuffCountDeductCondition,
    CombatStatType,
)
from battle.objects.models import (
    CharacterId,
    DamageData,
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
        apply_timing: Optional[RoundPhaseType] = None,
    ):
        self.move_list: list[MoveData] = move_list
        self.damage_data_list: list[DamageCalculateData] = [
            DamageCalculateData(damage_data, []) for damage_data in damage_list
        ]
        self.heal_data_list: list[HealCalculateData] = [
            HealCalculateData(heal_data, []) for heal_data in heal_list
        ]
        self.buff_add_data_list: list[BuffAddData] = buff_add_list
        self.apply_timing: Optional[RoundPhaseType] = apply_timing


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
                data_per_effect.apply_timing,
            )
            for data_per_effect in data.data_per_effect
            if data_per_effect is not None
        ]

        # 대미지 리다이렉트(도발/희생 방어) 결과. {원래 대상: 치환 대상}
        # 같은 커맨드(스킬)의 buff_add 등 부가 효과도 이 매핑을 따라 함께 이동한다.
        self._redirect_map: dict[CharacterId, CharacterId] = {}

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
                    self._process_damage(i)
                    self._process_heal(i)
                    self._process_all_buff_add(i)
                # ENEMY_POST_ACTION effect는 이 페이즈에서 처리하지 않음

        elif phase == RoundPhaseType.ALLY_ACTION:
            for i in range(len(self.data_by_effect)):
                self._process_move(i)
                self._process_damage(i)
                self._process_heal(i)
                self._process_buff_add(i, phase)

        elif phase == RoundPhaseType.ENEMY_POST_ACTION:
            for i in range(len(self.data_by_effect)):
                timing = self.data_by_effect[i].apply_timing
                if timing is None:
                    # 아군 스킬 동작: 대미지/힐과 POST 타이밍 버프만 처리 (이동은 PRE에서 완료)
                    self._process_damage(i)
                    self._process_heal(i)
                    self._process_buff_add(i, phase)
                elif timing == RoundPhaseType.ENEMY_POST_ACTION:
                    # 에너미 스킬 POST effect: 전체 처리
                    self._process_move(i)
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
                self._process_damage(i)
                self._process_heal(i)

    def _process_move(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        for move_data in self.data_by_effect[effect_seq_number].move_list:
            self.context.move_character_to(
                move_data.character_id, move_data.to_position
            )
            if not move_data.is_forced:
                self.context.buff_container.on_voluntary_move(move_data.character_id)

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
                final = self._resolve_redirect(damage_calc.base.attacker_id, original)
                if final != original:
                    damage_calc.base = replace(damage_calc.base, target_id=final)
                    self._redirect_map[original] = final

    def _resolve_redirect(
        self: "CommandPartCalculator",
        attacker_id: CharacterId,
        original_target: CharacterId,
    ) -> CharacterId:
        """도발(공격자 기준) → 희생 방어(대상 기준) 순으로 최종 대상을 결정한다."""
        final = original_target
        # 도발: 공격자가 도발 상태면 도발자를 노린다.
        taunt_target = self._get_target_override(attacker_id)
        if taunt_target is not None and taunt_target in self.context.characters:
            final = taunt_target
        # 희생 방어: 현재 대상이 보호 중이면 보호자가 대신 맞는다.
        protector = self._consume_sacrifice_protector(final)
        if protector is not None:
            final = protector
        return final

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
    ) -> Optional[CharacterId]:
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
            return protector
        return None

    def _process_damage(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        # 대상 치환(도발/희생 방어)은 process() 시작 시 _prepare_redirects에서 일괄 수행됨.
        for damage_calc in list(
            self.data_by_effect[effect_seq_number].damage_data_list
        ):
            self._apply_buff_events(
                effect_seq_number,
                damage_calc.base.attacker_id,
                BuffCountDeductCondition.ON_ATTACK,
                damage_calc.base.target_id,
            )
            self._apply_buff_events(
                effect_seq_number,
                damage_calc.base.target_id,
                BuffCountDeductCondition.ON_HIT,  # noqa: F821
                damage_calc.base.attacker_id,
            )
        for damage_calc in self.data_by_effect[effect_seq_number].damage_data_list:
            attacker = self.context.characters[damage_calc.base.attacker_id]
            target = self.context.characters[damage_calc.base.target_id]

            is_magic_attack = (
                damage_calc.base.is_magic_attack
                if damage_calc.base.is_magic_attack is not None
                else attacker.status.is_magic_attacker
            )
            if is_magic_attack:
                damage_calc.modifiers.append(target.status.m_res)

            damage_calc.result_value = self.context.apply_damage(
                damage_calc.base.attacker_id,
                damage_calc.base.target_id,
                ValueWithModifiers(damage_calc.base.value, damage_calc.modifiers),
                self,
                effect_seq_number,
            )

    def _process_heal(self: "CommandPartCalculator", effect_seq_number: int) -> None:
        for heal_calc in list(self.data_by_effect[effect_seq_number].heal_data_list):
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
        for heal_calc in self.data_by_effect[effect_seq_number].heal_data_list:
            heal_calc.result_value = self.context.apply_heal(
                heal_calc.base.healer_id,
                heal_calc.base.target_id,
                ValueWithModifiers(heal_calc.base.value, heal_calc.modifiers),
                self,
                effect_seq_number,
            )

    def _process_buff_add(
        self: "CommandPartCalculator",
        effect_seq_number: int,
        phase: RoundPhaseType,
    ) -> None:
        buff_add_list = self.data_by_effect[effect_seq_number].buff_add_data_list
        if phase == RoundPhaseType.ALLY_ACTION:
            for data in buff_add_list:
                self.context.buff_container.add(self._redirect_applied_to(data))
        elif phase == RoundPhaseType.ENEMY_PRE_ACTION:
            for data in buff_add_list:
                if data.add_timing == RoundPhaseType.ENEMY_PRE_ACTION:
                    self.context.buff_container.add(self._redirect_applied_to(data))
        elif phase == RoundPhaseType.ENEMY_POST_ACTION:
            for data in buff_add_list:
                if data.add_timing == RoundPhaseType.ENEMY_POST_ACTION:
                    self.context.buff_container.add(self._redirect_applied_to(data))
        else:
            raise ValueError(f"Cannot add buffs at this phase: {phase}")

    def _process_all_buff_add(
        self: "CommandPartCalculator",
        effect_seq_number: int,
    ) -> None:
        """apply_timing이 명시된 에너미 스킬 effect용: buff_add_timing에 무관하게 모두 추가."""
        for data in self.data_by_effect[effect_seq_number].buff_add_data_list:
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
        events = [buff.create_event() for buff in buffs]
        events.sort(key=lambda e: e.priority.value)
        for event in events:
            if event.is_applied(self.context, char_id, attacker_or_target):
                event.apply(char_id, attacker_or_target, self, effect_seq_number)

        if deduct_condition is not None:
            for buff in buffs:
                buff.duration.deduct_count(deduct_condition)
                if buff.duration.finished:
                    self.context.buff_container.remove(buff.uid)
