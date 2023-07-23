from __future__ import annotations

import asyncio
import logging
import os
import ssl
import sys
import aiomqtt
from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper
from caseta_to_mqtt.caseta import topology
from caseta_to_mqtt.caseta.button_watcher import ButtonTracker

from caseta_to_mqtt.caseta.topology import BridgeConfiguration, Topology
from caseta_to_mqtt.z2m.state import StateManager
from caseta_to_mqtt.z2m.client import Zigbee2mqttClient

_LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()
_HANDLER = logging.StreamHandler(stream=sys.stderr)
_HANDLER.setLevel(_LOGLEVEL)
_FORMATTER = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
_HANDLER.setFormatter(_FORMATTER)
logging.basicConfig(level=_LOGLEVEL, handlers=[_HANDLER])
LOGGER = logging.getLogger(__name__)

PATH_TO_CERT_FILE: str = os.environ.get("PATH_TO_LUTRON_CLIENT_CERT")
PATH_TO_KEY_FILE: str = os.environ.get("PATH_TO_LUTRON_CLIENT_KEY")
PATH_TO_CA_FILE: str = os.environ.get("PATH_TO_LUTRON_CA_CERT")

PATH_TO_PIHOME_CERT_FILE: str = os.environ.get("PATH_TO_MQTT_CLIENT_CERT")
PATH_TO_PIHOME_KEY_FILE: str = os.environ.get("PATH_TO_MQTT_CLIENT_KEY")
PATH_TO_PIHOME_CA_FILE: str = os.environ.get("PATH_TO_MQTT_CA")

MQTT_HOST: str = os.environ.get("MQTT_HOST")
MQTT_PORT: int = int(os.environ.get("MQTT_PORT"))
MQTT_USERNAME: str = os.environ.get("MQTT_USERNAME")
MQTT_PASSWORD: str = os.environ.get("MQTT_PASSWORD")

CASETA_BRIDGE_HOSTNAME = "caseta.run"


async def main_loop():
    shutdown_latch_wrapper = ShutdownLatchWrapper()

    bridge_configuration = BridgeConfiguration(
        CASETA_BRIDGE_HOSTNAME, PATH_TO_KEY_FILE, PATH_TO_CERT_FILE, PATH_TO_CA_FILE
    )

    state_manager: StateManager = StateManager()
    LOGGER.info("connecting to mqtt broker")
    async with asyncio.TaskGroup() as task_group:
        async with aiomqtt.Client(
            MQTT_HOST,
            MQTT_PORT,
            username=MQTT_USERNAME,
            password=MQTT_PASSWORD,
            tls_params=aiomqtt.TLSParameters(
                ca_certs=PATH_TO_PIHOME_CA_FILE,
                certfile=PATH_TO_PIHOME_CERT_FILE,
                keyfile=PATH_TO_PIHOME_KEY_FILE,
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
            ),
        ) as mqtt_client:
            z2m_client = Zigbee2mqttClient(
                mqtt_client, state_manager, shutdown_latch_wrapper
            )
            button_tracker = ButtonTracker(shutdown_latch_wrapper, z2m_client)

            smartbridge = topology.default_bridge(bridge_configuration)
            caseta_topology = Topology(
                smartbridge, button_tracker, shutdown_latch_wrapper
            )
            LOGGER.info("connecting to caseta bridge")
            await caseta_topology.connect()
            LOGGER.info("done connecting to caseta bridge")
            task_group.create_task(z2m_client.subscribe_to_zigbee2mqtt_messages())
            # task_group.create_task(publisher.publish_loop())
            LOGGER.info("done connecting to mqtt broker")
            caseta_topology.load_callbacks()
            LOGGER.info
            await shutdown_latch_wrapper.wait()
            LOGGER.info("received shutdown signal. shutting down")
            await smartbridge.close()


if __name__ == "__main__":
    asyncio.run(main_loop())
