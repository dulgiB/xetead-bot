from dataclasses import KW_ONLY, dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

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

    targets: list[CharacterId] | list[BattlefieldColumnIndex] = field(
        default_factory=list
    )


@dataclass(frozen=True)
class CommandPartDataPerEffect:
    move_list: list[MoveData] = field(default_factory=list)
    damage_list: list[DamageData] = field(default_factory=list)
    heal_list: list[HealData] = field(default_factory=list)
    buff_add_list: list[BuffAddData] = field(default_factory=list)
    buff_remove_list: list[BuffRemoveData] = field(default_factory=list)
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
                    )
                )
        return CommandPartData(
            original_part=self.original_part,
            data_per_effect=tuple(new_data_per_effect_list),
        )


@dataclass
class DamageCalculateData:
    base: DamageData
    modifiers: list[ValueModifierBase]
    result_value: Optional[int] = None
    # 주사위 굴림을 포함한 계산식 표기 (ValueWithModifiers.__str__). 로그 기록용.
    roll_display: Optional[str] = None


@dataclass
class HealCalculateData:
    base: HealData
    modifiers: list[ValueModifierBase]
    result_value: Optional[int] = None
    # 주사위 굴림을 포함한 계산식 표기 (ValueWithModifiers.__str__). 로그 기록용.
    roll_display: Optional[str] = None


@dataclass
class BuffRemoveCalculateData:
    base: BuffRemoveData
    result_value: Optional[int] = None


@dataclass(frozen=True)
class BattleLogEntry:
    """로그_전투 시트 한 행에 대응하는 정산 결과 (대상 1명당 1개)."""

    target_name: str
    result: str
    roll_display: Optional[str] = None


@dataclass(frozen=True)
class CommandPartProcessResult:
    expanded_part: CommandPartData
    log_entries: list[BattleLogEntry] = field(default_factory=list)


@dataclass(frozen=True)
class CommandProcessResult:
    original_command: CharacterCommand
    part_results: list[CommandPartProcessResult]
