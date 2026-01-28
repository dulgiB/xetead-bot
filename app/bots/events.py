from dataclasses import dataclass


@dataclass
class SendMessageEvent:
    message: str
