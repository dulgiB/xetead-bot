import abc
import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Optional, Type, cast

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import (
    FATE_INTERVENTION_SKILL_BONUS,
    MAX_EFFECT_COUNT,
    BattlefieldColumnIndex,
    FateBoostMode,
    SkillTargetOverrideType,
    ValueSourceType,
)
from battle.objects.models import CharacterId, DamageData, HealData, MoveData
from battle.objects.skill.define import SkillValueType
from battle.objects.skill.target_functions import SkillTargetRule
from utils.spreadsheet_bool import parse_spreadsheet_bool
from utils.spreadsheet_row import SpreadsheetRow

if TYPE_CHECKING:
    from battle.core.battlefield_context import BattlefieldContext
    from battle.objects.buff.conditions import Condition


@dataclass(frozen=True)
class SkillEffectBase(abc.ABC):
    value_source: Optional[ValueSourceType]
    value: Optional[int]
    value_type: Optional[SkillValueType]
    buff_id: Optional[str]
    buff_add_timing: Optional[
        Literal[RoundPhaseType.ENEMY_PRE_ACTION, RoundPhaseType.ENEMY_POST_ACTION]
    ]
    target_override: Optional[SkillTargetOverrideType] = None
    # 에너미 스킬 전용. None이면 페이즈별 기본값을 쓰는 아군 스킬 동작.
    apply_timing: Optional[
        Literal[RoundPhaseType.ENEMY_PRE_ACTION, RoundPhaseType.ENEMY_POST_ACTION]
    ] = None
    # 적층형 버프 부여/제거 시 한 번에 적용할 스택 상한
    buff_stack_cap: Optional[int] = None
    # 즉시 평가 가능한 Condition만 여기 남는다 — ConsumedBuffStackCountCondition은
    # 파싱 시점에 아래 gate_value_source/gate_value로 변환된다.
    condition_class_name: Optional[str] = None
    condition_value: Optional[int] = None
    # 커맨드 처리 중간값(지금까지 소모된 스택 합 등)에 의존해 expand() 시점엔
    # 평가할 수 없는 조건을 위한 지연 게이트.
    gate_value_source: Optional[ValueSourceType] = None
    gate_value: Optional[int] = None
    # 다른 버프의 스택 수를 새 버프의 수치로 스냅샷하는 등, 다른 버프 id를
    # 참조하는 효과 전용.
    reference_buff_id: Optional[str] = None
    # 대상이 이미 보유하고 있어야 하는 버프 id(선행 디버프 존재를 요구하는
    # 콤보용 게이트). buff_id(이 효과가 부여/조회하는 버프)와는 별개다.
    required_target_buff_id: Optional[str] = None
    # 열 광역 target_rule은 command_expanders.py가 따로 True를 강제하므로,
    # 이 필드는 개체 지정 효과에서 도발을 무시해야 할 때만 켠다(둘은 OR).
    ignores_taunt: bool = False
    # 자멸형 자기 대미지가 시전자 본인의 방어 패시브에 막히지 않게 하는 용도.
    # DamageData.triggers_holder_action_buffs로 전달된다.
    ignores_defensive_buffs: bool = False

    # 조건이 아니라 효과 본체가 damaged_this_round 같은 데이터를 직접 읽을 때
    # 켠다 — PassiveSkillWrapperBuff가 평가 시점을 고르는 데 쓴다.
    requires_round_resolved: ClassVar[bool] = False

    @property
    def condition(self) -> Optional["Condition"]:
        if not self.condition_class_name:
            return None
        condition_module = importlib.import_module("battle.objects.buff.conditions")
        condition_class: Type["Condition"] = getattr(
            condition_module, self.condition_class_name
        )
        return condition_class(value=self.condition_value)

    @abc.abstractmethod
    def _expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
        raw_targets: "tuple[CharacterId | BattlefieldColumnIndex, ...]" = (),
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
        list[BuffRemoveData],
    ]:
        pass

    def expand(
        self,
        context: "BattlefieldContext",
        holder: CharacterId,
        targets: list[CharacterId],
        raw_targets: "tuple[CharacterId | BattlefieldColumnIndex, ...]" = (),
    ) -> tuple[
        list[MoveData],
        list[DamageData],
        list[HealData],
        list[BuffAddData],
        list[BuffRemoveData],
    ]:
        if self.target_override is None:
            return self._expand(context, holder, targets, raw_targets)

        if self.target_override == SkillTargetOverrideType.SELF:
            return self._expand(context, holder, [holder], raw_targets)

        raise ValueError(self.target_override)

    def get_debuff_clear_targets(
        self,
        context: "BattlefieldContext",
        targets: list[CharacterId],
    ) -> list[CharacterId]:
        """디버프를 일괄 제거하는 효과(SkillEffectRemoveDebuffs)만 오버라이드한다.

        expand() 호출 **전에** 불러야 한다 — expand()가 즉시 디버프를 지우므로,
        "무엇이 지워질지"는 지우기 전에 확정해야 답글에 정확히 표시할 수 있다.
        기본 구현은 대부분의 효과에 해당 사항이 없으므로 빈 리스트를 반환한다.
        """
        return []


_EnemyPhase = Literal[RoundPhaseType.ENEMY_PRE_ACTION, RoundPhaseType.ENEMY_POST_ACTION]


def parse_skill_effect(data: SpreadsheetRow, index: int) -> Optional[SkillEffectBase]:
    """스프레드시트 행에서 index번째 효과(effect_{index} 등)를 파싱한다.

    스킬(effect_0~2)과 아이템(effect_0) 양쪽에서 재사용된다.
    effect_{index} 컬럼이 비어 있으면 None을 반환한다.
    """
    effect_name = data.get(f"effect_{index}")
    if not effect_name:
        return None

    skill_effect_module = importlib.import_module("battle.objects.skill.effects")
    effect: Type[SkillEffectBase] = getattr(skill_effect_module, str(effect_name))

    value_source = (
        ValueSourceType(data[f"value_source_{index}"])
        if data.get(f"value_source_{index}")
        else None
    )
    value_raw = data.get(f"value_{index}") or None
    value = int(value_raw) if value_raw is not None else None
    value_type = (
        SkillValueType(data[f"value_type_{index}"])
        if data.get(f"value_type_{index}")
        else None
    )
    # 스킬_캐릭터/스킬_패시브는 buff_id_{index}, 스킬_에너미는 buff_name_{index}를 쓴다.
    buff_id_raw = data.get(f"buff_id_{index}") or data.get(f"buff_name_{index}") or None
    buff_id = str(buff_id_raw) if buff_id_raw is not None else None
    buff_add_timing = (
        cast(_EnemyPhase, RoundPhaseType(data[f"buff_add_timing_{index}"]))
        if data.get(f"buff_add_timing_{index}")
        else None
    )
    target_override = (
        SkillTargetOverrideType(data[f"target_override_{index}"])
        if data.get(f"target_override_{index}")
        else None
    )
    apply_timing_raw = data.get(f"effect_apply_timing_{index}")
    apply_timing = (
        cast(_EnemyPhase, RoundPhaseType(apply_timing_raw))
        if apply_timing_raw
        else None
    )
    buff_stack_cap = (
        int(data[f"buff_stack_cap_{index}"])
        if data.get(f"buff_stack_cap_{index}")
        else None
    )

    condition_class_name_raw = data.get(f"condition_{index}") or None
    condition_class_name = (
        str(condition_class_name_raw) if condition_class_name_raw is not None else None
    )
    condition_value = (
        int(data[f"condition_value_{index}"])
        if data.get(f"condition_value_{index}")
        else None
    )
    gate_value_source: Optional[ValueSourceType] = None
    gate_value: Optional[int] = None
    if condition_class_name == "ConsumedBuffStackCountCondition":
        # 커맨드 처리 중간값에만 의존하므로 일반 Condition이 아니라
        # 게이트 파이프라인으로 넘긴다.
        gate_value_source = ValueSourceType.CONSUMED_BUFF_STACK
        gate_value = condition_value
        condition_class_name = None
        condition_value = None

    reference_buff_id_raw = data.get(f"reference_buff_id_{index}") or None
    reference_buff_id = (
        str(reference_buff_id_raw) if reference_buff_id_raw is not None else None
    )
    required_target_buff_id_raw = data.get(f"required_target_buff_id_{index}") or None
    required_target_buff_id = (
        str(required_target_buff_id_raw)
        if required_target_buff_id_raw is not None
        else None
    )
    ignores_taunt = parse_spreadsheet_bool(data.get(f"ignores_taunt_{index}", False))
    ignores_defensive_buffs = parse_spreadsheet_bool(
        data.get(f"ignores_defensive_buffs_{index}", False)
    )

    return effect(
        value_source=value_source,
        value=value,
        value_type=value_type,
        buff_id=buff_id,
        buff_add_timing=buff_add_timing,
        target_override=target_override,
        apply_timing=apply_timing,
        buff_stack_cap=buff_stack_cap,
        condition_class_name=condition_class_name,
        condition_value=condition_value,
        gate_value_source=gate_value_source,
        gate_value=gate_value,
        reference_buff_id=reference_buff_id,
        required_target_buff_id=required_target_buff_id,
        ignores_defensive_buffs=ignores_defensive_buffs,
        ignores_taunt=ignores_taunt,
    )


@dataclass(frozen=True)
class Skill:
    target_rule: SkillTargetRule
    data: "SkillData"


@dataclass(frozen=True)
class SkillData:
    id: str
    target_rule: str
    target_count: int
    cost: int
    effects: list[SkillEffectBase]
    description: str
    # False면 답글에서 설명을 블라인드 처리한다. 컬럼이 없는 시트
    # ("스킬_캐릭터" 등)는 항상 True(공개).
    revealed: bool = True
    # 예고 줄은 원래 에너미 전용이지만, True인 스킬은 아군이 선언해도 붙는다.
    reveal_effect: bool = False
    # True면 본문의 "▹ 대상 | 결과" 줄을 생략하고 헤더만 남긴다. 아군 전체를
    # 대상으로 하는 스킬처럼 줄 수가 불어나 본문이 통째로 잘려 나가는 경우에
    # 쓴다 — 수치는 계산식 쪽에 그대로 남는다.
    hide_result_lines: bool = False
    # 운명간섭("+")이 이 스킬에 무엇을 더해주는지. None이면 대미지 스킬은
    # 굴림 보정, 비대미지 스킬은 거부라는 기본 동작을 쓴다.
    fate_mode: Optional[FateBoostMode] = None
    # 모드별 보정치. 단위는 모드가 정한다 — VALUE_BOOST는 대상 효과의
    # value_type(퍼센트면 계수 %p), BUFF_*는 버프 수치/스택, EXTRA_TARGET은
    # 추가 대상 수. ROLL_BONUS에서만 생략 가능하다.
    fate_value: Optional[int] = None
    # VALUE_BOOST/BUFF_* 모드가 어느 효과(effect_N)를 강화하는지. 비우면 0.
    fate_effect_index: int = 0

    @classmethod
    def from_dict(cls, data: SpreadsheetRow) -> "SkillData":
        skill_effects: list[SkillEffectBase] = []

        for i in range(MAX_EFFECT_COUNT):
            if (effect := parse_skill_effect(data, i)) is not None:
                skill_effects.append(effect)

        return SkillData(
            id=str(data["id"]),
            target_rule=str(data["target_rule"]),
            target_count=int(data["target_count"]),
            cost=int(data["cost"]),
            effects=skill_effects,
            description=str(data["description"]),
            revealed=parse_spreadsheet_bool(data.get("is_revealed", True)),
            reveal_effect=parse_spreadsheet_bool(data.get("reveal_effect", False)),
            hide_result_lines=parse_spreadsheet_bool(
                data.get("hide_result_lines", False)
            ),
            # 컬럼이 없는 "스킬_에너미"는 기본값으로 남는다 — 에너미는
            # 부활 횟수가 0이라 애초에 운명간섭을 쓸 수 없다.
            fate_mode=(
                FateBoostMode(str(data["fate_mode"]).strip())
                if str(data.get("fate_mode", "") or "").strip()
                else None
            ),
            fate_value=(
                int(data["fate_value"])
                if str(data.get("fate_value", "") or "").strip()
                else None
            ),
            fate_effect_index=(
                int(data["fate_effect_index"])
                if str(data.get("fate_effect_index", "") or "").strip()
                else 0
            ),
        )

    def to_skill_instance(
        self, context: "BattlefieldContext", holder: CharacterId
    ) -> Skill:
        target_rule_module = importlib.import_module(
            "battle.objects.skill.target_functions"
        )
        rule: Type[SkillTargetRule] = getattr(target_rule_module, self.target_rule)
        return Skill(target_rule=rule(context, holder), data=self)

    @property
    def fate_effect(self) -> Optional[SkillEffectBase]:
        """fate_effect_index가 가리키는 효과. 범위를 벗어나면 None."""
        if 0 <= self.fate_effect_index < len(self.effects):
            return self.effects[self.fate_effect_index]
        return None

    @property
    def fate_boost_value(self) -> int:
        """모드별 보정치. ROLL_BONUS에서만 생략을 허용하고 기본값으로 채운다."""
        if self.fate_value is not None:
            return self.fate_value
        return FATE_INTERVENTION_SKILL_BONUS


def fate_config_error(data: SkillData) -> Optional[str]:
    """스킬의 운명간섭 설정이 실제로 동작할 수 있는 조합인지 확인하고, 문제가
    있으면 사람이 읽을 설명을 반환한다(없으면 None).

    조용히 무시되는 시트 설정을 만들지 않기 위한 것으로, 전투 개시 시점에
    admin에게 미리 알리는 용도다 — 실제 커맨드 처리 중에 발견하면 그때는
    플레이어가 이미 "+"를 붙여 선언한 뒤라 되돌리기가 번거롭다. 그래서
    BattlefieldContext(전장)가 아직 없는 시점에도 부를 수 있도록 SkillData만
    받는다.
    """
    mode = data.fate_mode
    if mode is None:
        return None

    if mode is not FateBoostMode.ROLL_BONUS and data.fate_value is None:
        return (
            f"'{data.id}': fate_mode가 '{mode.value}'인데 fate_value가 비어 있습니다."
        )
    if data.fate_value is not None and data.fate_value <= 0:
        return f"'{data.id}': fate_value는 1 이상이어야 합니다."

    if mode is FateBoostMode.EXTRA_TARGET:
        target_rule_module = importlib.import_module(
            "battle.objects.skill.target_functions"
        )
        rule: Type[SkillTargetRule] = getattr(target_rule_module, data.target_rule)
        if rule.ignores_input_targets:
            return (
                f"'{data.id}': target_rule({data.target_rule})은 대상을 입력받지 않아"
                " '대상 추가'를 적용할 수 없습니다."
            )
        return None

    if mode in (
        FateBoostMode.VALUE_BOOST,
        FateBoostMode.BUFF_VALUE_BOOST,
        FateBoostMode.BUFF_STACK_BOOST,
    ):
        effect = data.fate_effect
        if effect is None:
            return (
                f"'{data.id}': fate_effect_index({data.fate_effect_index})에 해당하는"
                f" effect_{data.fate_effect_index}가 비어 있습니다."
            )
        if (
            mode in (FateBoostMode.BUFF_VALUE_BOOST, FateBoostMode.BUFF_STACK_BOOST)
            and effect.buff_id is None
        ):
            return (
                f"'{data.id}': effect_{data.fate_effect_index}가 버프를 부여하지 않아"
                f" '{mode.value}'를 적용할 수 없습니다."
            )
    return None
