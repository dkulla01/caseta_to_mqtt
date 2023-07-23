from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Callable
from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper

from caseta_to_mqtt.caseta import (
    BUTTON_WATCHER_MAX_DURATION,
    BUTTON_WATCHER_SLEEP_DURATION,
    DOUBLE_CLICK_WINDOW,
)
from caseta_to_mqtt.caseta.model import (
    ButtonAction,
    ButtonHistory,
    ButtonId,
    ButtonState,
)
from caseta_to_mqtt.z2m.client import Zigbee2mqttClient

LOGGER = logging.getLogger(__name__)


class ButtonWatcher:
    def __init__(
        self, button_history: ButtonHistory, zigbee2mqtt_client: Zigbee2mqttClient
    ) -> ButtonWatcher:
        self._button_history = button_history
        self._zigbee2mqtt_client: zigbee2mqtt_client

    async def button_watcher_loop(self) -> None:
        button_history = self._button_history

        button_log_prefix = (
            f"remote: {button_history.remote_id}, button:{button_history.button_id}"
        )

        button_tracking_window_end = datetime.now() + BUTTON_WATCHER_MAX_DURATION
        await asyncio.sleep(DOUBLE_CLICK_WINDOW.total_seconds())
        async with button_history.mutex:
            current_state = button_history.button_state
            if current_state == ButtonState.FIRST_PRESS_AND_FIRST_RELEASE:
                LOGGER.debug(f"{button_log_prefix}: A single press has completed")
                button_history.is_finished = True
                # await self._zigbee2mqtt_client.turn_on_group(Zigbee2mqttGroup())
                return
            elif current_state == ButtonState.FIRST_PRESS_AWAITING_RELEASE:
                LOGGER.debug(
                    f"{button_log_prefix}: a long press has started but not finished"
                )
            elif current_state == ButtonState.DOUBLE_PRESS_FINISHED:
                LOGGER.debug(f"{button_log_prefix}: A double press has completed")
                button_history.is_finished = True
                return
            else:
                LOGGER.debug(f"{button_log_prefix}: current state is {current_state}")
        while datetime.now() < button_tracking_window_end:
            await asyncio.sleep(BUTTON_WATCHER_SLEEP_DURATION.total_seconds())
            async with button_history.mutex:
                current_state = button_history.button_state
                if current_state == ButtonState.FIRST_PRESS_AND_FIRST_RELEASE:
                    LOGGER.debug(f"{button_log_prefix}: a long press has completed")
                    button_history.is_finished = True
                    return
                elif current_state == ButtonState.FIRST_PRESS_AWAITING_RELEASE:
                    LOGGER.debug(f"{button_log_prefix}: a long press is still ongoing")
                    # todo: perform long press action
                elif current_state == ButtonState.DOUBLE_PRESS_FINISHED:
                    LOGGER.debug(f"{button_log_prefix}: a double press has completed")
                    button_history.is_finished = True
                    return
                else:
                    LOGGER.debug(
                        f"{button_log_prefix}: current state is {current_state}"
                    )
        async with button_history.mutex:
            button_history.is_finished = True
        LOGGER.debug(
            f"{button_log_prefix}: the button tracking window ended without the button reaching a terminal state"
        )

    async def increment_history(self, button_action: ButtonAction):
        await self._button_history.increment(button_action)


class ButtonTracker:
    def __init__(
        self,
        shutdown_latch_wrapper: ShutdownLatchWrapper,
        zigbee2mqtt_client: Zigbee2mqttClient,
    ):
        self._mutex = asyncio.Lock()
        self._shutdown_latch_wrapper: ShutdownLatchWrapper = shutdown_latch_wrapper
        self._button_watchers_by_remote_id: dict[str, ButtonWatcher] = dict()
        self._zigbee2mqtt_client = zigbee2mqtt_client

    def button_event_callback(
        self, remote_id: str, button_id: ButtonId
    ) -> Callable[[str], None]:
        return lambda button_event_str: asyncio.get_running_loop().create_task(
            self._process_button_event(
                remote_id, button_id, ButtonAction.of_str(button_event_str)
            )
        )

    async def _process_button_event(
        self, remote_id: str, button_id: ButtonId, button_action: ButtonAction
    ):
        await self._shutdown_latch_wrapper.wrap_with_shutdown_latch(
            self._inner_process_button_event(remote_id, button_id, button_action)
        )

    async def _inner_process_button_event(
        self, remote_id: str, button_id: ButtonId, button_action: ButtonAction
    ):
        LOGGER.info(
            f"got a button event: remote_id: {remote_id}, button_id: {button_id}, button_action: {button_action}"
        )

        async with self._mutex:
            button_watcher: ButtonWatcher = self._button_watchers_by_remote_id.get(
                remote_id
            )

            if (
                not button_watcher
                or not button_watcher._button_history
                or button_watcher._button_history.is_finished
                or button_watcher._button_history.is_timed_out
            ):
                button_watcher = ButtonWatcher(
                    ButtonHistory(remote_id, button_id), self._zigbee2mqtt_client
                )
                await button_watcher.increment_history(button_action)
                asyncio.ensure_future(
                    self._shutdown_latch_wrapper.wrap_with_shutdown_latch(
                        button_watcher.button_watcher_loop()
                    )
                )
            else:
                await button_watcher.increment_history(button_action)
            self._button_watchers_by_remote_id[remote_id] = button_watcher
