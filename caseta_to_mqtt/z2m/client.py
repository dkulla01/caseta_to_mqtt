from datetime import datetime, timedelta
import json
import logging
from typing import Optional
import aiomqtt
from caseta_to_mqtt.asynchronous.mutex_wrapper import MutexWrapped

from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper
from caseta_to_mqtt.z2m.model import (
    GroupState,
    OnOrOff,
    Zigbee2mqttGroup,
    Zigbee2mqttScene,
)
from caseta_to_mqtt.z2m.state import AllGroups, GroupStateManager

LOGGER = logging.getLogger(__name__)


class Zigbee2mqttClient:
    _GET_STATE_MESSAGE_BODY: str = json.dumps({"state": {}})
    _TURN_ON_MESSAGE_BODY: str = json.dumps({"state": OnOrOff.ON.as_str()})
    _TURN_OFF_MESSAGE_BODY: str = json.dumps({"state": OnOrOff.OFF.as_str()})

    def __init__(
        self,
        mqtt_client: aiomqtt.Client,
        group_state_manager: GroupStateManager,
        all_groups: AllGroups,
        shutdown_latch_wrapper: ShutdownLatchWrapper,
    ):
        self._mqtt_client: aiomqtt.Client = mqtt_client
        self._group_state_manager = group_state_manager
        self._shutdown_latch_wrapper: ShutdownLatchWrapper = shutdown_latch_wrapper
        self._all_groups: AllGroups = all_groups

    async def subscribe_to_zigbee2mqtt_messages(self):
        async with self._mqtt_client.messages() as messages:
            # listen for new groups
            await self._mqtt_client.subscribe("zigbee2mqtt/bridge/groups")
            async for message in messages:
                if message.topic.matches("zigbee2mqtt/bridge/groups"):
                    await self._handle_groups_response(message)

                else:
                    current_groups = await self._all_groups.get_groups()
                    if any(
                        message.topic.matches(group.topic) for group in current_groups
                    ):
                        LOGGER.debug(f"got message for topic: {message.topic}")
                        deserialized_group_response = (
                            json.loads(message.payload) if message.payload else {}
                        )
                        group_name = Zigbee2mqttGroup.friendly_name_from_topic_name(
                            message.topic.value
                        )

                        now = datetime.now()

                        # todo: this should be the first configured scene, not "none"
                        current_scene = None
                        current_group_state: MutexWrapped[Optional[GroupState]] = None
                        async with self._group_state_manager.get_group_state() as group_states_by_friendly_name:
                            if group_name not in group_states_by_friendly_name:
                                group_states_by_friendly_name[
                                    group_name
                                ] = MutexWrapped(None)
                            current_group_state = group_states_by_friendly_name.get(
                                group_name
                            )

                        async with current_group_state.get() as locked_group_state:
                            if not locked_group_state.value or (
                                now - locked_group_state.value.updated_at
                                > timedelta(seconds=60)
                            ):
                                locked_group_state.value = GroupState(
                                    brightness=None,
                                    state=OnOrOff.from_str(
                                        deserialized_group_response.get("state")
                                    ),
                                    scene=None,
                                    updated_at=now,
                                )
                            else:
                                current_value = locked_group_state.value
                                locked_group_state.value = GroupState(
                                    brightness=deserialized_group_response.get(
                                        "brightness"
                                    )
                                    or current_value.brightness,
                                    state=OnOrOff.from_str(
                                        deserialized_group_response.get("state")
                                    )
                                    or current_value.state,
                                    scene=current_value.scene,
                                    updated_at=now,
                                )
                    LOGGER.debug("done handling message for topic %s", message.topic)

    async def _handle_groups_response(self, message: aiomqtt.Message):
        groups_response = json.loads(message.payload) if message.payload else []
        LOGGER.debug(f"got message for topic: {message.topic}")
        all_groups: set[Zigbee2mqttGroup] = set()
        for group in groups_response:
            scenes = [
                Zigbee2mqttScene(scene["id"], scene["name"])
                for scene in group["scenes"]
            ]
            new_group = Zigbee2mqttGroup(group["id"], group["friendly_name"], scenes)
            all_groups.add(new_group)
            await self._mqtt_client.subscribe(new_group.topic)
            await self._mqtt_client.publish(
                f"{new_group.topic}/get", json.dumps({"state": ""})
            )

        await self._all_groups.update_groups(all_groups)

    async def turn_on_group(self, group: Zigbee2mqttGroup):
        await self._mqtt_client.publish(
            f"{group.topic}/set", Zigbee2mqttClient._TURN_ON_MESSAGE_BODY
        )

    async def turn_off_group(self, group: Zigbee2mqttGroup):
        await self._mqtt_client.publish(
            f"{group.topic}/set", Zigbee2mqttClient._TURN_OFF_MESSAGE_BODY
        )

    async def publish_get_loop_state_message(self, group: Zigbee2mqttGroup):
        await self._mqtt_client.publish(
            f"{group.topic}/get", Zigbee2mqttClient._GET_STATE_MESSAGE_BODY
        )
