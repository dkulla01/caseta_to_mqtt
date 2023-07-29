from dataclasses import dataclass
from enum import Enum
import logging
from typing import Optional

from dynaconf import Dynaconf
from caseta_to_mqtt.caseta.model import ButtonId, PicoRemote

from caseta_to_mqtt.z2m.client import Zigbee2mqttClient
from caseta_to_mqtt.z2m.model import Zigbee2mqttGroup
from caseta_to_mqtt.z2m.state import AllGroups, GroupStateManager

LOGGER = logging.getLogger(__name__)


class UnknownRoomError(Exception):
    pass


class ButtonEvent(Enum):
    SINGLE_PRESS_COMPLETED = 0
    LONG_PRESS_ONGOING = 1
    LONG_PRESS_FINISHED = 3
    DOUBLE_PRESS_FINISHED = 4


_LONG_PRESS_BUTTON_EVENTS: set[ButtonEvent] = {
    ButtonEvent.LONG_PRESS_ONGOING,
    ButtonEvent.LONG_PRESS_FINISHED,
}


@dataclass(frozen=True)
class CasetaEvent:
    remote: PicoRemote
    button_id: ButtonId
    button_event: ButtonEvent


class EventHandler:
    def __init__(
        self,
        z2m_client: Zigbee2mqttClient,
        all_groups: AllGroups,
        group_state_manager: GroupStateManager,
        settings: Dynaconf,
    ):
        self._z2m_client: Zigbee2mqttClient = z2m_client
        self._all_groups: AllGroups = all_groups
        self._group_state_manager: GroupStateManager = group_state_manager
        self._settings: Dynaconf = settings

    async def translate_caseta_room_to_z2m_room(
        self, remote_name: str
    ) -> Optional[Zigbee2mqttGroup]:
        z2m_groups = await self._all_groups.get_groups()
        z2m_groups_by_friendly_name = {
            group.friendly_name: group for group in z2m_groups
        }

        if remote_name in z2m_groups_by_friendly_name:
            return z2m_groups_by_friendly_name[remote_name]

        z2m_group_name_maybe = self._settings.caseta_to_room_mappings.get(remote_name)
        if z2m_group_name_maybe:
            return z2m_groups_by_friendly_name.get(z2m_group_name_maybe)

    async def handle_event(self, event: CasetaEvent):
        z2m_group = await self.translate_caseta_room_to_z2m_room(event.remote.name)
        if not z2m_group:
            raise UnknownRoomError(
                f"unable to find a z2m group assigned to remote: {event.remote}"
            )

        match event.button_id:
            case ButtonId.POWER_ON:
                await self.handle_power_on_event(z2m_group, event)
            case ButtonId.POWER_OFF:
                await self.handle_power_off_event(z2m_group, event)
            case ButtonId.FAVORITE:
                await self.handle_favorite_button_event(z2m_group, event)
            case _:
                LOGGER.info(
                    "%s %s; we haven't implemented handling for other buttons yet",
                    event.remote,
                    event.button_event,
                )

    @staticmethod
    def _ensure_correct_button(desired_button_id: ButtonId, event: ButtonEvent):
        if event.button_id != desired_button_id:
            raise AssertionError(
                f"expecting ButtonId: {desired_button_id}, but received {event}"
            )

    async def handle_power_on_event(
        self, z2m_group: Zigbee2mqttGroup, event: CasetaEvent
    ):
        EventHandler._ensure_correct_button(ButtonId.POWER_ON, event)
        if event.button_event in _LONG_PRESS_BUTTON_EVENTS:
            LOGGER.debug("no action necessary for long press ButtonEvent: %s", event)
            return
        await self._z2m_client.turn_on_group(z2m_group)

    async def handle_power_off_event(
        self, z2m_group: Zigbee2mqttGroup, event: CasetaEvent
    ):
        EventHandler._ensure_correct_button(ButtonId.POWER_OFF, event)
        if event.button_event in _LONG_PRESS_BUTTON_EVENTS:
            LOGGER.debug("no action necessary for long press ButtonEvent: %s", event)
            return
        await self._z2m_client.turn_off_group(z2m_group)

    async def handle_favorite_button_event(
        self, z2m_group: Zigbee2mqttGroup, event: CasetaEvent
    ):
        EventHandler._ensure_correct_button(ButtonId.FAVORITE, event)
        if event.button_event in _LONG_PRESS_BUTTON_EVENTS:
            LOGGER.debug("no action necessary for long press ButtonEvent: %s", event)
            return
