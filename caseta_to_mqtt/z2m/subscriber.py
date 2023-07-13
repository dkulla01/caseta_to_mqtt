import json
import logging
import aiomqtt

from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper
from caseta_to_mqtt.z2m.model import Zigbee2mqttGroup, Zigbee2mqttScene

LOGGER = logging.getLogger(__name__)


class Zigbee2mqttSubscriber:
    def __init__(
        self, mqtt_client: aiomqtt.Client, shutdown_latch_wrapper: ShutdownLatchWrapper
    ):
        self._mqtt_client: aiomqtt.Client = mqtt_client
        self._shutdown_latch_wrapper: ShutdownLatchWrapper = shutdown_latch_wrapper
        self._all_groups: set[Zigbee2mqttGroup] = set()

    def get_state(self) -> dict[str, Zigbee2mqttGroup]:
        return {group.friendly_name: group for group in self._all_groups}

    async def subscribe_to_zigbee2mqtt_messages(self):
        async with self._mqtt_client as client:
            async with client.messages() as messages:
                # listen for new groups
                await client.subscribe("zigbee2mqtt/bridge/groups")
                # I think this is handling messages one-at-a-time, so we won't have any concurrent messages creating
                # race conditions (i.e. since we're only processing messages one at a time, we don't need to do any locking
                # on the set of groups, the state of groups/scenes/brightnesses/etc)
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
                            await client.subscribe(new_group.topic)
                    elif any(
                        message.topic.matches(group.topic) for group in self._all_groups
                    ):
                        deserialized_group_response = (
                            json.loads(message.payload) if message.payload else {}
                        )
                        LOGGER.debug(f"got message for topic: {message.topic}")
