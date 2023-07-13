from __future__ import annotations
from dataclasses import dataclass
import itertools
import logging
from typing import Union

from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper
from pylutron_caseta.smartbridge import Smartbridge

from caseta_to_mqtt.caseta.button_watcher import ButtonTracker
from caseta_to_mqtt.caseta.model import (
    ButtonId,
    PicoRemote,
    PicoThreeButtonRaiseLower,
    PicoTwoButton,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BridgeConfiguration:
    caseta_bridge_hostname: str
    caseta_key_file: str
    caseta_cert_file: str
    caseta_ca_file: str


def default_bridge(bridge_configuration: BridgeConfiguration) -> Smartbridge:
    return Smartbridge.create_tls(
        bridge_configuration.caseta_bridge_hostname,
        bridge_configuration.caseta_key_file,
        bridge_configuration.caseta_cert_file,
        bridge_configuration.caseta_ca_file,
    )


class Topology:
    def __init__(
        self,
        caseta_bridge: Smartbridge,
        button_tracker: ButtonTracker,
        shutdown_latch_wrapper: ShutdownLatchWrapper,
    ) -> Topology:
        self._caseta_bridge: Smartbridge = caseta_bridge
        self._button_tracker: ButtonTracker = button_tracker
        self._shutdown_latch_wrapper: ShutdownLatchWrapper = shutdown_latch_wrapper
        self._is_initialized = False
        self._remotes_by_id: dict[int, PicoRemote] = {}

    async def connect(self) -> None:
        if self._is_initialized:
            LOGGER.debug("connection is already initialized")
            return

        LOGGER.info("connecting to caseta bridge")
        connection_future = self._caseta_bridge.connect()
        await self._shutdown_latch_wrapper.wrap_with_shutdown_latch(connection_future)
        self._is_initialized = True
        all_buttons = self._caseta_bridge.get_buttons()
        all_devices = self._caseta_bridge.get_devices()
        for device_id, device in all_devices.items():
            # some devices don't have any remotes (e.g. the bridge itself). skip them
            if device_id not in self._buttons_by_remote_id.keys():
                continue

            remote_buttons = all_buttons[device["device_id"]]
            buttons_by_id = {
                button["device_id"]: ButtonId.of_int(button["button_number"])
                for button in remote_buttons
            }

            if device["type"] == PicoThreeButtonRaiseLower.TYPE:
                self._remotes_by_id[device_id] = PicoThreeButtonRaiseLower(
                    int(device_id), device["name"], buttons_by_id
                )
            elif device["type"] == PicoTwoButton.TYPE:
                self._remotes_by_id[device_id] = PicoTwoButton(
                    int(device_id), device["name"], buttons_by_id
                )
        LOGGER.info("done connecting to caseta bridge")

    @property
    def remotes_by_id(self):
        if not self._is_initialized:
            raise AssertionError("Topology has not been initialized yet")
        return self._remotes_by_id

    def _load_topology_callbacks(self):
        for remote_id, buttons in self._buttons_by_remote_id.items():
            [
                self._caseta_bridge.add_button_subscriber(
                    button["device_id"],
                    self._button_tracker.button_event_callback(
                        remote_id, ButtonId.of_int(button["button_number"])
                    ),
                )
                for button in buttons
            ]
