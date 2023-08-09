from datetime import datetime
import json
import logging
from typing import Optional
import aiomqtt

from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper
from caseta_to_mqtt.z2m.model import (
    Brightness,
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

    async def subscribe_to_zigbee2mqtt_messages(self) -> None:
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
                        await self._handle_single_group_response(message)

    async def _handle_single_group_response(self, message: aiomqtt.Message):
        LOGGER.debug("got message for topic: %s", message.topic)

        payload: str | bytearray | bytes
        if isinstance(message.payload, (str, bytearray, bytes)):
            payload = message.payload
        else:
            raise AssertionError(
                f"expected deserializable json, but got {type(message.payload)}"
            )
        deserialized_group_response = json.loads(payload) if message.payload else {}
        group_name = Zigbee2mqttGroup.friendly_name_from_topic_name(message.topic.value)

        now = datetime.now()
        brightness_maybe: Optional[Brightness] = (
            Brightness(int(deserialized_group_response["brightness"]))
            if "brightness" in deserialized_group_response
            else None
        )
        on_or_off_state = OnOrOff.from_str(deserialized_group_response.get("state"))

        await self._group_state_manager.update_group_state(
            group_name,
            GroupState(
                brightness=brightness_maybe,
                state=on_or_off_state,
                scene=None,
                updated_at=now,
            ),
        )
        LOGGER.debug("done handling message for topic %s", message.topic)

    async def _handle_groups_response(self, message: aiomqtt.Message):
        payload: str | bytearray | bytes
        if isinstance(message.payload, (str, bytearray, bytes)):
            payload = message.payload
        else:
            raise AssertionError(
                f"expected deserializable json, but got {type(message.payload)}"
            )
        groups_response = json.loads(payload)  # if message.payload else []
        LOGGER.debug("got message for topic: %s", message.topic)
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

    async def recall_scene(self, group: Zigbee2mqttGroup, scene: Zigbee2mqttScene):
        scene_recall_payload = json.dumps({"scene_recall": scene.id})
        await self._mqtt_client.publish(
            f"{group.topic}/set", payload=scene_recall_payload
        )

    async def set_brightness(self, group: Zigbee2mqttGroup, brightness: Brightness):
        await self._mqtt_client.publish(
            f"{group.topic}/set", payload=json.dumps(brightness.as_z2m_message())
        )
