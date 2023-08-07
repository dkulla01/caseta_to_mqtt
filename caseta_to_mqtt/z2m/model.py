from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Optional


@dataclass(frozen=True)
class Zigbee2mqttScene:
    id: int
    friendly_name: str


@dataclass(frozen=True)
class Zigbee2mqttGroup:
    id: int
    friendly_name: str
    scenes: list[Zigbee2mqttScene]

    @property
    def topic(self) -> str:
        return f"zigbee2mqtt/{self.friendly_name}"

    @staticmethod
    def friendly_name_from_topic_name(topic_name: str):
        return topic_name.removeprefix("zigbee2mqtt/")

    def __key(self) -> tuple:
        return (
            self.id,
            self.friendly_name,
            tuple(f"{scene.id}-{scene.friendly_name}" for scene in self.scenes),
        )

    def __hash__(self) -> int:
        return hash(self.__key())


class OnOrOff(StrEnum):
    OFF = "off"
    ON = "on"

    def as_str(self):
        return self.value

    @classmethod
    def from_str(cls, str_literal) -> OnOrOff:
        return cls[str_literal.upper()]


@dataclass(frozen=True, kw_only=True)
class GroupState:
    brightness: Optional[int]
    state: OnOrOff
    scene: Optional[Zigbee2mqttScene]
    updated_at: datetime
