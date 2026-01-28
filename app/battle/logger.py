from dataclasses import dataclass

from battle.objects.models import CharacterId


class Logger:
    pass


@dataclass
class CommandResult:
    character_id: CharacterId
