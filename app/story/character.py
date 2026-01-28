from dataclasses import dataclass
from enum import Enum

from app.utils.dice import nd6


class NoncombatStatType(Enum):
    INS = 1
    WSD = 2
    LUK = 3


@dataclass
class NoncombatStats:
    instinct: int  # 직감
    wisdom: int  # 지혜
    luck: int  # 행운

    def roll(self, stat_type: NoncombatStatType):
        if stat_type == NoncombatStatType.INS:
            return nd6(1, bonus=self.instinct)
        if stat_type == NoncombatStatType.WSD:
            return nd6(1, bonus=self.wisdom)
        if stat_type == NoncombatStatType.LUK:
            return nd6(1, bonus=self.luck)


@dataclass
class Item:
    name: str
    desc: str
    quantity: int


class NoncombatCharacter:
    inventory: list[Item]
    deposit: int
    status: NoncombatStats
