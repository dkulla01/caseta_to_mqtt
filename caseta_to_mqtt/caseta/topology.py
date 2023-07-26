from __future__ import annotations
import itertools
import logging

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


def default_bridge(
    hostname: str, path_to_key_file: str, path_to_cert_file: str, path_to_ca_file: str
) -> Smartbridge:
    return Smartbridge.create_tls(
        hostname,
        path_to_key_file,
        path_to_cert_file,
        path_to_ca_file,
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
        buttons_by_remote_id = {
            remote_id: list(buttons)
            for remote_id, buttons in itertools.groupby(
                [button for button in all_buttons.values()],
                lambda b: b["parent_device"],
            )
        }

        for device_id, device in all_devices.items():
            # some devices are not remotes, so skip them
            if device_id not in buttons_by_remote_id.keys():
                continue

            remote_buttons = buttons_by_remote_id[device["device_id"]]
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
            else:
                LOGGER.debug(
                    "device: %s: device type `%s` is not a supported pico remote and will be skipped",
                    device["name"],
                    device["type"],
                )
        LOGGER.info("done connecting to caseta bridge")

    @property
    def remotes_by_id(self):
        if not self._is_initialized:
            raise AssertionError("Topology has not been initialized yet")
        return self._remotes_by_id

    def load_callbacks(self):
        for remote in self.remotes_by_id.values():
            if isinstance(remote, PicoThreeButtonRaiseLower):
                self._load_three_button_raise_lower_callback(remote)
            elif isinstance(remote, PicoTwoButton):
                self._load_two_button_callback(remote)
            else:
                raise AssertionError(f"unable to load callbacks for device {remote}")

    def _load_three_button_raise_lower_callback(
        self, remote: PicoThreeButtonRaiseLower
    ):
        for button_id, button in remote.buttons_by_button_id.items():
            self._caseta_bridge.add_button_subscriber(
                str(button_id),
                self._button_tracker.button_event_callback(
                    str(remote.device_id), button
                ),
            )

    def _load_two_button_callback(self, remote: PicoTwoButton):
        pass

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
