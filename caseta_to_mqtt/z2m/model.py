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


class Brightness:
    MINIMUM: Brightness
    MAXIMUM: Brightness
    _MINIMUM_VALUE: int = 1
    _MAXIMUM_VALUE: int = 254
    _STEP_SIZE = 16

    def __init__(self, value: int):
        if (
            not isinstance(value, int)
            or value < Brightness._MINIMUM_VALUE
            or value > Brightness._MAXIMUM_VALUE
        ):
            raise AssertionError(f"{value} is not a valid brightness value")
        self._value = value

    def next_higher_value(self) -> Brightness:
        next_higher_value: int = min(
            self._value + Brightness._STEP_SIZE, Brightness._MAXIMUM_VALUE
        )
        return Brightness(next_higher_value)

    def next_lower_value(self) -> Brightness:
        next_lower_value: int = max(
            self._value - Brightness._STEP_SIZE, Brightness._MINIMUM_VALUE
        )
        return Brightness(next_lower_value)

    def as_z2m_message(self) -> dict[str, int]:
        return {"brightness": self._value}


Brightness.MINIMUM = Brightness(Brightness._MINIMUM_VALUE)
Brightness.MAXIMUM = Brightness(Brightness._MAXIMUM_VALUE)


@dataclass(frozen=True, kw_only=True)
class GroupState:
    brightness: Optional[Brightness]
    state: OnOrOff
    scene: Optional[Zigbee2mqttScene]
    updated_at: datetime
