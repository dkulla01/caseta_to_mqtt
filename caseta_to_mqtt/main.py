from __future__ import annotations

import asyncio
import itertools
import logging
import os
import ssl
import sys
import aiomqtt
from pylutron_caseta.smartbridge import Smartbridge
from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper
from caseta_to_mqtt.caseta import topology
from caseta_to_mqtt.caseta.button_watcher import ButtonTracker

from caseta_to_mqtt.caseta.topology import BridgeConfiguration, Topology

LOGGER = logging.getLogger(__name__)
_LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()
LOGGER.setLevel(_LOGLEVEL)
_HANDLER = logging.StreamHandler(stream=sys.stderr)
_FORMATTER = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
_HANDLER.setFormatter(_FORMATTER)
LOGGER.addHandler(_HANDLER)

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

    button_tracker = ButtonTracker(shutdown_latch_wrapper)

    bridge_configuration = BridgeConfiguration(
        CASETA_BRIDGE_HOSTNAME, PATH_TO_KEY_FILE, PATH_TO_CERT_FILE, PATH_TO_CA_FILE
    )

    smartbridge = topology.default_bridge(bridge_configuration)
    caseta_topology = Topology(smartbridge, button_tracker, ShutdownLatchWrapper)
    await caseta_topology.connect()

    async with asyncio.TaskGroup() as task_group:
        mqtt_client = aiomqtt.Client(
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
        )
        task_group.create_task(
            Zigbee2mqttSubscriber(
                mqtt_client, shutdown_latch
            ).subscribe_to_zigbee2mqtt_messages()
        )
        publisher = Zigbee2mqttPublisher(mqtt_client)
        task_group.create_task(publisher.publish_loop())

    async with shutdown_latch:
        await shutdown_latch.wait()
        LOGGER.info("received shutdown signal. shutting down")
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(main_loop())
