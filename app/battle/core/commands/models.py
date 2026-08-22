from dataclasses import KW_ONLY, dataclass, field
from enum import Enum
from typing import Literal, Optional

from battle.core.commands.define import RoundPhaseType
from battle.objects.buff.buff_base import BuffAddData, BuffRemoveData
from battle.objects.define import MAX_EFFECT_COUNT, ActionType, BattlefieldColumnIndex
from battle.objects.models import (
    BuffUid,
    CharacterId,
    DamageData,
    HealData,
    MoveData,
    ValueModifierBase,
)

# user input -> parse() -> list[CommandBase] -> expand_xxx_command() ->
# list[CommandData] -> process_xxx_command() -> list[CommandProcessResult]


@dataclass(frozen=True)
class CharacterCommand:
    user_id: CharacterId
    parts: list["CommandPart"]


@dataclass(frozen=True)
class CommandPart:
    type_: ActionType

    _: KW_ONLY
    # 스킬과 아이템은 id = name
    skill_id: Optional[str] = None
    item_id: Optional[str] = None

    # 대부분의 커맨드는 한 종류만 담지만, SkillTargetRuleNamedWithColumn처럼
    # 캐릭터 이름과 열을 한 커맨드에 함께 지정하는 경우가 있어 원소별로
    # 섞일 수 있는 타입이다(list[A] | list[B]가 아니라 list[A | B]).
    targets: list[CharacterId | BattlefieldColumnIndex] = field(default_factory=list)


@dataclass(frozen=True)
class CommandPartDataPerEffect:
    move_list: list[MoveData] = field(default_factory=list)
    damage_list: list[DamageData] = field(default_factory=list)
    heal_list: list[HealData] = field(default_factory=list)
    buff_add_list: list[BuffAddData] = field(default_factory=list)
    buff_remove_list: list[BuffRemoveData] = field(default_factory=list)
    # SkillEffectRemoveDebuffs가 디버프를 일괄 제거한 대상 (답글 표시용).
    debuff_clear_list: list[CharacterId] = field(default_factory=list)
    # 에너미 스킬 전용: None이면 페이즈별 기본값(이동→PRE, 대미지/힐→POST) 사용.
    apply_timing: Optional[
        Literal[RoundPhaseType.ENEMY_PRE_ACTION, RoundPhaseType.ENEMY_POST_ACTION]
    ] = None


@dataclass
class CommandPartData:
    original_part: Optional[CommandPart]

    _: KW_ONLY
    data_per_effect: tuple[Optional[CommandPartDataPerEffect], ...] = field(
        default_factory=lambda: tuple(None for _ in range(MAX_EFFECT_COUNT))
    )

    admin_target_phase: Optional[RoundPhaseType] = None
    admin_buff_remove_list: list[BuffUid] = field(default_factory=list)

    def __post_init__(self):
        assert len(self.data_per_effect) <= MAX_EFFECT_COUNT

        if len(self.data_per_effect) < MAX_EFFECT_COUNT:
            padded_data = [data for data in self.data_per_effect]
            while len(padded_data) != MAX_EFFECT_COUNT:
                padded_data.append(None)
            self.data_per_effect = tuple(padded_data)

    def create_new_except_move(self) -> "CommandPartData":
        new_data_per_effect_list: list[Optional[CommandPartDataPerEffect]] = []

        for data in self.data_per_effect:
            if data is None:
                continue

            if data.apply_timing is not None:
                # 에너미 스킬: apply_timing이 명시된 effect는 process()가 페이즈를 보고 처리 여부를 결정하므로 그대로 보존
                new_data_per_effect_list.append(data)
            else:
                new_data_per_effect_list.append(
                    CommandPartDataPerEffect(
                        move_list=[],
                        damage_list=data.damage_list,
                        heal_list=data.heal_list,
                        buff_add_list=data.buff_add_list,
                        buff_remove_list=data.buff_remove_list,
                        debuff_clear_list=data.debuff_clear_list,
                    )
                )
        return CommandPartData(
            original_part=self.original_part,
            data_per_effect=tuple(new_data_per_effect_list),
        )


@dataclass
class DamageCalculateData:
    base: DamageData
    # 공격자(holder)가 주는 대미지에 적용되는 modifier (BuffGivenDamage 등)
    given_modifiers: list[ValueModifierBase] = field(default_factory=list)
    # 대상(holder)이 받는 대미지에 적용되는 modifier (BuffReceivedDamage, m_res, 희생 방어 등)
    received_modifiers: list[ValueModifierBase] = field(default_factory=list)
    result_value: Optional[int] = None
    # 주사위 굴림을 포함한 계산식 표기 (ValueWithModifiers.format_calculation()). 로그 기록용.
    roll_display: Optional[str] = None
    # 대미지 적용 직후의 대상 HP/최대 HP 스냅샷. 같은 커맨드에서 같은 대상이
    # 여러 번 맞을 수 있어(예: 스킬 효과 2개), 답글 포매터가 나중에
    # context를 다시 조회하면 최종 HP만 보이게 되므로 그 시점 값을 남겨둔다.
    hp_after: Optional[int] = None
    max_hp: Optional[int] = None


@dataclass
class HealCalculateData:
    base: HealData
    # 회복 시전자(holder)가 주는 회복에 적용되는 modifier (BuffGivenHeal 등).
    # "받는 회복" 버프는 아직 없어 받는 쪽 그룹은 두지 않는다.
    given_modifiers: list[ValueModifierBase] = field(default_factory=list)
    result_value: Optional[int] = None
    # 주사위 굴림을 포함한 계산식 표기 (ValueWithModifiers.format_calculation()). 로그 기록용.
    roll_display: Optional[str] = None
    # 회복 적용 직후의 대상 HP/최대 HP 스냅샷 (DamageCalculateData.hp_after 참고).
    hp_after: Optional[int] = None
    max_hp: Optional[int] = None


@dataclass
class BuffRemoveCalculateData:
    base: BuffRemoveData
    result_value: Optional[int] = None


class BattleLogEntryKind(str, Enum):
    DAMAGE = "damage"
    HEAL = "heal"
    MOVE = "move"
    BUFF_ADD = "buff_add"
    BUFF_REMOVE = "buff_remove"
    DEBUFF_CLEAR = "debuff_clear"
    # 방어막/반사 등 BuffNoDataBase 계열이 대미지/회복을 완전히 무효화해
    # damage_data_list/heal_data_list에서 항목 자체가 사라졌을 때, "왜 대미지가
    # 안 보이는지"를 답글에 남기기 위한 종류.
    NO_EFFECT = "no_effect"


@dataclass(frozen=True)
class BattleLogEntry:
    """로그_전투 시트 한 행에 대응하는 정산 결과 (대상 1명당 1개).

    `result`/`roll_display`는 로그_전투 시트 기록용 텍스트로 그대로 유지한다.
    `kind`와 나머지 구조화 필드는 봇 답글 포매터(app/bot/battle_reply_text.py)가
    `entry.result` 문자열을 접두사로 재해석하지 않고 종류별로 바로 분기할 수
    있도록 하기 위한 것이다.
    """

    target_name: str
    kind: BattleLogEntryKind
    result: str
    roll_display: Optional[str] = None
    value: Optional[int] = None  # damage/heal 최종 수치
    buff_id: Optional[str] = None  # buff_add/buff_remove
    stack_delta: Optional[int] = (
        None  # buff_add: 이번에 추가된 스택 / buff_remove: 이번에 소모된 스택
    )
    # buff_add(적층형 버프 한정): 답글 포매터가 같은 (대상, buff_id) 조합의
    # 여러 부여를 "[라벨]×합계 부여 → 최종 M" 한 줄로 합칠 때 쓴다.
    # entry.result를 다시 파싱하지 않도록 라벨/최종 스택을 구조화 필드로 둔다.
    buff_label: Optional[str] = None
    final_stack: Optional[int] = None
    # damage/heal 적용 직후의 대상 HP/최대 HP 스냅샷. 같은 커맨드에서 같은
    # 대상이 여러 번 맞을/회복될 수 있어(효과 2개 이상), 답글 포매터가
    # 나중에 context를 다시 조회하면 최종 HP만 보이게 되므로 이 시점 값을
    # 그대로 들고 있는다.
    hp_after: Optional[int] = None
    max_hp: Optional[int] = None
    # 반격/반사/코모이디아류처럼 제3자(버프 보유자)가 대신 가한 대미지의
    # 발생 원인 라벨들(DamageData.source_label을 모아 중복 제거한 것). 답글
    # 요약 줄에 "[라벨]"로 덧붙인다 — 캐릭터 본인의 직접 행동이면 비어 있다.
    source_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandPartProcessResult:
    expanded_part: CommandPartData
    log_entries: list[BattleLogEntry] = field(default_factory=list)
    # 도발 등으로 대미지 대상이 치환된 (원래 대상 → 실제 대상) 매핑
    # (CommandPartCalculator._prepare_redirects()가 계산). 답글 포매터
    # (app/bot/battle_reply_text.py)가 헤더에 "원래 대상 ▸ 실제 대상"을
    # 보여주는 데 쓴다.
    redirect_map: dict[CharacterId, CharacterId] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandProcessResult:
    original_command: CharacterCommand
    part_results: list[CommandPartProcessResult]
