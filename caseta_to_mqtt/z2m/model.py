
from dataclasses import dataclass


@dataclass(frozen=True)
class Zigbee2MqttScene:
    id: int
    friendly_name: str


@dataclass(frozen=True)
class Zigbee2MqttGroup:
    id: int
    friendly_name: str
    scenes: list[Zigbee2MqttScene]

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
