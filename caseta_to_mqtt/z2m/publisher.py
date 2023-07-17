from __future__ import annotations
import asyncio
import json
import logging

import aiomqtt
from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper

from caseta_to_mqtt.z2m.model import OnOrOff, Zigbee2mqttGroup


LOGGER = logging.getLogger(__name__)


class Zigbee2mqttPublisher:
    _GET_STATE_MESSAGE_BODY: str = json.dumps({"state": {}})
    _TURN_ON_MESSAGE_BODY: str = json.dumps({"state": OnOrOff.ON.as_str()})
    _TURN_OFF_MESSAGE_BODY: str = json.dumps({"state": OnOrOff.OFF.as_str()})

    def __init__(
        self, mqtt_client: aiomqtt.Client, shutdown_latch_wrapper: ShutdownLatchWrapper
    ) -> Zigbee2mqttPublisher:
        self._mqtt_client = mqtt_client
        self._shutdown_latch_wrapper = shutdown_latch_wrapper

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
                f"{group.topic}/get", Zigbee2mqttPublisher._GET_STATE_MESSAGE_BODY
            )

    async def publish_loop(self):
        while True:
            LOGGER.info("sleeping, then turning on")
            await asyncio.sleep(2)
            # await self.turn_on_group(group)
            LOGGER.info("sleeping, then turning off")
            await asyncio.sleep(2)
            # await self.turn_off_group(group)
