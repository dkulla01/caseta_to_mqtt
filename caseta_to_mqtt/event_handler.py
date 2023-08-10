from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging
from typing import Callable, Optional

from dynaconf import Dynaconf
from caseta_to_mqtt.caseta.model import ButtonId, PicoRemote

from caseta_to_mqtt.z2m.client import Zigbee2mqttClient
from caseta_to_mqtt.z2m.model import (
    Brightness,
    GroupState,
    OnOrOff,
    Zigbee2mqttGroup,
    Zigbee2mqttScene,
)
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


@dataclass(frozen=True)
class PreviousAndNextScene:
    previous: Zigbee2mqttScene
    next: Zigbee2mqttScene


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

        return None

    async def handle_event(self, event: CasetaEvent):
        z2m_group = await self.translate_caseta_room_to_z2m_room(event.remote.name)
        if not z2m_group:
            raise UnknownRoomError(
                f"unable to find a z2m group assigned to remote: {event.remote}"
            )

        match event.button_id:
            case ButtonId.POWER_ON:
                await self._handle_power_on_event(z2m_group, event)
            case ButtonId.POWER_OFF:
                await self._handle_power_off_event(z2m_group, event)
            case ButtonId.FAVORITE:
                await self._handle_favorite_button_event(z2m_group, event)
            case ButtonId.INCREASE | ButtonId.DECREASE:
                await self._handle_brightness_change_button_event(z2m_group, event)
            case _:
                LOGGER.info(
                    "%s %s; we haven't implemented handling for other buttons yet",
                    event.remote,
                    event.button_event,
                )

    @staticmethod
    def _ensure_correct_button(desired_button_id: ButtonId, event: CasetaEvent):
        if event.button_id != desired_button_id:
            raise AssertionError(
                f"expecting ButtonId: {desired_button_id}, but received {event}"
            )

    async def _handle_power_on_event(
        self, z2m_group: Zigbee2mqttGroup, event: CasetaEvent
    ):
        EventHandler._ensure_correct_button(ButtonId.POWER_ON, event)
        if event.button_event in _LONG_PRESS_BUTTON_EVENTS:
            LOGGER.debug("no action necessary for long press ButtonEvent: %s", event)
            return
        await self._z2m_client.turn_on_group(z2m_group)

    async def _handle_power_off_event(
        self, z2m_group: Zigbee2mqttGroup, event: CasetaEvent
    ):
        EventHandler._ensure_correct_button(ButtonId.POWER_OFF, event)
        if event.button_event in _LONG_PRESS_BUTTON_EVENTS:
            LOGGER.debug("no action necessary for long press ButtonEvent: %s", event)
            return
        await self._z2m_client.turn_off_group(z2m_group)

    async def _handle_brightness_change_button_event(
        self, z2m_group: Zigbee2mqttGroup, event: CasetaEvent
    ):
        current_group_state = await self._group_state_manager.get_group_state(
            z2m_group.friendly_name
        )
        if not current_group_state:
            raise AssertionError("todo -- should this init an empty group? idk")
        async with current_group_state.get() as locked_current_group_state:
            now = datetime.now()

            # turn on the group if it isn't on already
            if (
                not locked_current_group_state.value
                or locked_current_group_state.value.state != OnOrOff.ON
            ):
                await self._z2m_client.turn_on_group(z2m_group)
                return
            current_brightness = locked_current_group_state.value.brightness
            brightness_range_end: Brightness
            next_brightness_value_fn: Callable[[Brightness], Brightness]

            # are we increasing brightness or decreasing brightness?
            if event.button_id == ButtonId.INCREASE:
                brightness_range_end = Brightness.MAXIMUM
                next_brightness_value_fn = Brightness.next_higher_value
                pass
            else:
                brightness_range_end = Brightness.MINIMUM
                next_brightness_value_fn = Brightness.next_lower_value

            # figure out the next brightness value
            next_brightness_value: Brightness
            if not current_brightness:
                next_brightness_value = brightness_range_end
            else:
                next_brightness_value = next_brightness_value_fn(current_brightness)

            if event.button_event == ButtonEvent.DOUBLE_PRESS_FINISHED:
                next_brightness_value = next_brightness_value_fn(next_brightness_value)

            await self._z2m_client.set_brightness(z2m_group, next_brightness_value)
            locked_current_group_state.value = GroupState(
                brightness=next_brightness_value,
                state=OnOrOff.ON,
                scene=locked_current_group_state.value.scene,
                updated_at=now,
            )

    async def _handle_favorite_button_event(
        self, z2m_group: Zigbee2mqttGroup, event: CasetaEvent
    ):
        EventHandler._ensure_correct_button(ButtonId.FAVORITE, event)
        if event.button_event in _LONG_PRESS_BUTTON_EVENTS:
            LOGGER.debug("no action necessary for long press ButtonEvent: %s", event)
            return

        current_group_state = await self._group_state_manager.get_group_state(
            z2m_group.friendly_name
        )
        if not current_group_state:
            raise AssertionError("todo -- should this init an empty group?")
        async with current_group_state.get() as locked_current_group_state:
            previous_and_next_scene = await self._determine_previous_and_next_scenes(
                z2m_group.friendly_name, locked_current_group_state.value
            )
            LOGGER.debug("previous_and_next_scene: %s", previous_and_next_scene)
            next_scene_to_use: Zigbee2mqttScene
            if event.button_event == ButtonEvent.SINGLE_PRESS_COMPLETED:
                next_scene_to_use = previous_and_next_scene.next
            else:
                if event.button_event != ButtonEvent.DOUBLE_PRESS_FINISHED:
                    raise AssertionError(
                        f"expected a double press event, but got {event.button_event}"
                    )
                next_scene_to_use = previous_and_next_scene.previous
            await self._z2m_client.recall_scene(z2m_group, next_scene_to_use)
            locked_current_group_state.value = GroupState(
                brightness=None,
                state=OnOrOff.ON,
                scene=next_scene_to_use,
                updated_at=datetime.now(),
            )

    async def _determine_previous_and_next_scenes(
        self, friendly_name: str, group_state: Optional[GroupState]
    ) -> PreviousAndNextScene:
        all_groups = await self._all_groups.get_groups()
        z2m_group: Optional[Zigbee2mqttGroup] = next(
            (group for group in all_groups if group.friendly_name == friendly_name),
            None,
        )

        if not z2m_group:
            raise AssertionError(f"no z2m group named {friendly_name} exists")

        if not group_state or not group_state.scene:
            return PreviousAndNextScene(z2m_group.scenes[0], z2m_group.scenes[0])

        current_scene_index: int = next(
            idx for idx, val in enumerate(z2m_group.scenes) if val == group_state.scene
        )

        if len(z2m_group.scenes) == 1:
            return PreviousAndNextScene(z2m_group.scenes[0], z2m_group.scenes[0])
        if current_scene_index == len(z2m_group.scenes) - 1:
            return PreviousAndNextScene(
                z2m_group.scenes[current_scene_index - 1], z2m_group.scenes[0]
            )
        elif current_scene_index == 0:
            return PreviousAndNextScene(z2m_group.scenes[-1], z2m_group.scenes[1])
        return PreviousAndNextScene(
            z2m_group.scenes[current_scene_index - 1],
            z2m_group.scenes[current_scene_index + 1],
        )
