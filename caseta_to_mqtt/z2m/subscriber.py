from datetime import datetime, timedelta
import json
import logging
import aiomqtt

from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper
from caseta_to_mqtt.z2m.model import (
    GroupState,
    OnOrOff,
    Zigbee2mqttGroup,
    Zigbee2mqttScene,
)
from caseta_to_mqtt.z2m.state import StateManager

LOGGER = logging.getLogger(__name__)


class Zigbee2mqttSubscriber:
    def __init__(
        self,
        mqtt_client: aiomqtt.Client,
        state_manager: StateManager,
        shutdown_latch_wrapper: ShutdownLatchWrapper,
    ):
        self._mqtt_client: aiomqtt.Client = mqtt_client
        self._state_manager = state_manager
        self._shutdown_latch_wrapper: ShutdownLatchWrapper = shutdown_latch_wrapper
        self._all_groups: set[Zigbee2mqttGroup] = set()

    def get_state(self) -> dict[str, Zigbee2mqttGroup]:
        return {group.friendly_name: group for group in self._all_groups}

    async def subscribe_to_zigbee2mqtt_messages(self):
        async with self._mqtt_client.messages() as messages:
            # listen for new groups
            await self._mqtt_client.subscribe("zigbee2mqtt/bridge/groups")
            async for message in messages:
                if message.topic.matches("zigbee2mqtt/bridge/groups"):
                    groups_response = (
                        json.loads(message.payload) if message.payload else []
                    )
                    LOGGER.debug(f"got message for topic: {message.topic}")
                    for group in groups_response:
                        scenes = [
                            Zigbee2mqttScene(scene["id"], scene["name"])
                            for scene in group["scenes"]
                        ]
                        new_group = Zigbee2mqttGroup(
                            group["id"], group["friendly_name"], scenes
                        )
                        self._all_groups.add(new_group)
                        await self._mqtt_client.subscribe(new_group.topic)
                        await self._mqtt_client.publish(
                            f"{new_group.topic}/get", json.dumps({"state": ""})
                        )
                elif any(
                    message.topic.matches(group.topic) for group in self._all_groups
                ):
                    deserialized_group_response = (
                        json.loads(message.payload) if message.payload else {}
                    )
                    group_name = Zigbee2mqttGroup.friendly_name_from_topic_name(
                        message.topic.value
                    )
                    current_state = self._state_manager.get_group_state(group_name)
                    if not current_state:
                        self._state_manager.initialize_group_state(group_name)
                        current_state = self._state_manager.get_group_state(
                            group_name
                        )

                    async with current_state.lock() as locked_group_state:
                        now = datetime.now()

                        # todo: this should be the first configured scene, not "none"
                        current_scene = None

                        if (
                            locked_group_state.state
                            and locked_group_state.state.scene
                            and now - locked_group_state.state.updated_at
                            < timedelta(seconds=60)
                        ):
                            current_scene = locked_group_state.state.scene
                        group_state = GroupState(
                            deserialized_group_response.get("brightness"),
                            OnOrOff.from_str(
                                deserialized_group_response.get("state")
                            ),
                            current_scene,
                            datetime.now(),
                        )
                        locked_group_state.state = group_state
                    LOGGER.debug(f"got message for topic: {message.topic}")
