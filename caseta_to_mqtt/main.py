from __future__ import annotations

import asyncio
import logging
import os
import ssl
import sys
import aiomqtt
from dynaconf import Dynaconf
from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper
from caseta_to_mqtt.caseta import topology
from caseta_to_mqtt.caseta.button_watcher import ButtonTracker

from caseta_to_mqtt.caseta.topology import Topology
from caseta_to_mqtt.config import settings as dynaconf_settings
from caseta_to_mqtt.z2m.state import StateManager
from caseta_to_mqtt.z2m.client import Zigbee2mqttClient

_LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()
_HANDLER = logging.StreamHandler(stream=sys.stderr)
_HANDLER.setLevel(_LOGLEVEL)
_FORMATTER = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
_HANDLER.setFormatter(_FORMATTER)
logging.basicConfig(level=_LOGLEVEL, handlers=[_HANDLER])
LOGGER = logging.getLogger(__name__)


async def main_loop(settings: Dynaconf):
    shutdown_latch_wrapper = ShutdownLatchWrapper()

    state_manager: StateManager = StateManager()
    LOGGER.info("connecting to mqtt broker")
    async with asyncio.TaskGroup() as task_group:
        async with aiomqtt.Client(
            settings.mqtt_hostname,
            settings.mqtt_port,
            username=settings.mqtt_username,
            password=settings.mqtt_password,
            tls_params=aiomqtt.TLSParameters(
                ca_certs=settings.path_to_mqtt_ca_file,
                certfile=settings.path_to_mqtt_cert_file,
                keyfile=settings.path_to_mqtt_key_file,
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
            ),
        ) as mqtt_client:
            z2m_client = Zigbee2mqttClient(
                mqtt_client, state_manager, shutdown_latch_wrapper
            )
            button_tracker = ButtonTracker(shutdown_latch_wrapper, z2m_client)

            smartbridge = topology.default_bridge(
                settings.caseta_bridge_hostname,
                settings.path_to_lutron_client_key,
                settings.path_to_lutron_client_cert,
                settings.path_to_lutron_ca_cert,
            )
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
    asyncio.run(main_loop(dynaconf_settings))
