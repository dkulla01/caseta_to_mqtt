from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Callable, Optional
from caseta_to_mqtt.asynchronous.mutex_wrapper import MutexWrapped
from caseta_to_mqtt.asynchronous.shutdown_latch import ShutdownLatchWrapper

from caseta_to_mqtt.caseta import (
    BUTTON_WATCHER_MAX_DURATION,
    BUTTON_WATCHER_SLEEP_DURATION,
    DOUBLE_CLICK_WINDOW,
)
from caseta_to_mqtt.caseta.model import (
    ButtonAction,
    ButtonId,
    ButtonState,
    IllegalStateTransitionError,
)

LOGGER = logging.getLogger(__name__)


class ButtonHistory:
    def __init__(self, remote_id: str, button_id: str) -> None:
        self.remote_id: str = remote_id
        self.button_id: str = button_id
        self.button_state: MutexWrapped[ButtonState] = MutexWrapped(
            ButtonState.NOT_PRESSED
        )
        self.tracking_started_at: Optional[datetime] = None
        self.is_finished: bool = False
        # self.mutex: asyncio.Lock = asyncio.Lock()

    async def increment(self, button_action: ButtonAction) -> None:
        async with self.button_state.get() as button_state:
            if not button_state.value.is_button_action_valid(button_action):
                raise IllegalStateTransitionError()
            if button_state.value == ButtonState.NOT_PRESSED:
                self.tracking_started_at = datetime.now()
            button_state.value = button_state.value.next_state()

    @property
    def is_timed_out(self) -> bool:
        return (
            self.tracking_started_at
            and (datetime.now() - self.tracking_started_at)
            > BUTTON_WATCHER_MAX_DURATION
        )


class ButtonWatcher:
    def __init__(self, button_history: ButtonHistory) -> ButtonWatcher:
        self.button_history = button_history

    async def button_watcher_loop(self) -> None:
        button_history = self.button_history

        button_log_prefix = (
            f"remote: {button_history.remote_id}, button:{button_history.button_id}"
        )

        button_tracking_window_end = datetime.now() + BUTTON_WATCHER_MAX_DURATION
        await asyncio.sleep(DOUBLE_CLICK_WINDOW.total_seconds())
        async with button_history.button_state.get() as locked_current_state:
            current_state = locked_current_state.value
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
            async with button_history.button_state.get() as locked_current_state:
                current_state = locked_current_state.value
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
        # async with button_history.mutex:
        button_history.is_finished = True
        LOGGER.debug(
            f"{button_log_prefix}: the button tracking window ended without the button reaching a terminal state"
        )

    async def increment_history(self, button_action: ButtonAction):
        await self.button_history.increment(button_action)


class ButtonTracker:
    def __init__(self, shutdown_latch_wrapper: ShutdownLatchWrapper):
        # self._mutex = asyncio.Lock()
        self._shutdown_latch_wrapper: ShutdownLatchWrapper = shutdown_latch_wrapper
        self._button_watchers_by_remote_id: MutexWrapped[
            dict[str, ButtonWatcher]
        ] = MutexWrapped(dict())

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

        async with self._button_watchers_by_remote_id.get() as button_watchers_by_remote_id:
            button_watcher: ButtonWatcher = button_watchers_by_remote_id.value.get(
                remote_id
            )

            if (
                not button_watcher
                or not button_watcher.button_history
                or button_watcher.button_history.is_finished
                or button_watcher.button_history.is_timed_out
            ):
                button_watcher = ButtonWatcher(ButtonHistory(remote_id, button_id))
                await button_watcher.increment_history(button_action)
                asyncio.ensure_future(
                    self._shutdown_latch_wrapper.wrap_with_shutdown_latch(
                        button_watcher.button_watcher_loop()
                    )
                )
            else:
                await button_watcher.increment_history(button_action)
            button_watchers_by_remote_id.value[remote_id] = button_watcher
