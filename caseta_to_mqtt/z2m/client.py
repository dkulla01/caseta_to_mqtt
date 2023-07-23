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
from caseta_to_mqtt.z2m.state import AllGroups, StateManager

LOGGER = logging.getLogger(__name__)


class Zigbee2mqttClient:
    _GET_STATE_MESSAGE_BODY: str = json.dumps({"state": {}})
    _TURN_ON_MESSAGE_BODY: str = json.dumps({"state": OnOrOff.ON.as_str()})
    _TURN_OFF_MESSAGE_BODY: str = json.dumps({"state": OnOrOff.OFF.as_str()})

    def __init__(
        self,
        mqtt_client: aiomqtt.Client,
        state_manager: StateManager,
        shutdown_latch_wrapper: ShutdownLatchWrapper,
    ):
        self._mqtt_client: aiomqtt.Client = mqtt_client
        self._state_manager = state_manager
        self._shutdown_latch_wrapper: ShutdownLatchWrapper = shutdown_latch_wrapper
        self._all_groups: AllGroups = AllGroups()

    def get_state(self) -> dict[str, Zigbee2mqttGroup]:
        return {group.friendly_name: group for group in self._all_groups}

    async def subscribe_to_zigbee2mqtt_messages(self):
        async with self._mqtt_client.messages() as messages:
            # listen for new groups
            await self._mqtt_client.subscribe("zigbee2mqtt/bridge/groups")
            async for message in messages:
                if message.topic.matches("zigbee2mqtt/bridge/groups"):
                    await self._handle_groups_response(message)
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
                        current_state = self._state_manager.get_group_state(group_name)

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
                            OnOrOff.from_str(deserialized_group_response.get("state")),
                            current_scene,
                            datetime.now(),
                        )
                        locked_group_state.state = group_state
                    LOGGER.debug(f"got message for topic: {message.topic}")

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
        async with self._mqtt_client as client:
            await client.publish(
                f"{group.topic}/set",
            )

    async def turn_off_group(self, group: Zigbee2mqttGroup):
        async with self._mqtt_client as client:
            await client.publish(group.topic, json.dumps({"on": False}))

    async def publish_get_loop_state_message(self, group: Zigbee2mqttGroup):
        async with self._mqtt_client as client:
            client.publish(
                f"{group.topic}/get", Zigbee2mqttClient._GET_STATE_MESSAGE_BODY
            )
