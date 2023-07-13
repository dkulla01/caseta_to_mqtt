from dataclasses import dataclass
from datetime import datetime
from enum import Enum


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

    def __key(self) -> tuple:
        (
            self.id,
            self.friendly_name,
            tuple(f"{scene.id}-{scene.friendly_name}" for scene in self.scenes),
        )

    def __hash__(self) -> int:
        return hash(self.__key())


class OnOrOff(Enum):
    OFF = 0
    ON = 1


@dataclass(frozen=True)
class GroupState:
    brightness: int
    state: OnOrOff
    scene: Zigbee2mqttScene
    updated_at: datetime
