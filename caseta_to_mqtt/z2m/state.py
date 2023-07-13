from __future__ import annotations
from asyncio import Lock
import logging
from typing import Iterable, Optional

from caseta_to_mqtt.z2m.model import GroupState, Zigbee2mqttGroup


LOGGER = logging.getLogger(__name__)


class StateManager:
    def __init__(self) -> StateManager:
        self._state: dict[str, GroupState] = {}

    def set_state(self, group_name: str, state: GroupState):
        self._state[group_name] = state

    def get_state(self, group_name) -> Optional[GroupState]:
        return self._state.get(group_name)
