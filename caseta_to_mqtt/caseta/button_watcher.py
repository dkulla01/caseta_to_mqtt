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

LOGGER = logging.getLogger(__name__)


async def button_watcher_loop(button_history: ButtonHistory) -> None:
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
                LOGGER.debug(f"{button_log_prefix}: current state is {current_state}")
    async with button_history.mutex:
        button_history.is_finished = True
    LOGGER.debug(
        f"{button_log_prefix}: the button tracking window ended without the button reaching a terminal state"
    )


class ButtonTracker:
    def __init__(self, shutdown_latch_wrapper: ShutdownLatchWrapper):
        self.mutex = asyncio.Lock()
        self.shutdown_latch_wrapper: ShutdownLatchWrapper = shutdown_latch_wrapper
        self.button_histories_by_remote_id: dict[str, ButtonHistory] = dict()

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
        LOGGER.info(
            f"got a button event: remote_id: {remote_id}, button_id: {button_id}, button_action: {button_action}"
        )

        async with self.mutex:
            button_history = self.button_histories_by_remote_id.get(remote_id)

            if (
                not button_history
                or button_history.is_finished
                or button_history.is_timed_out
            ):
                button_history = ButtonHistory(remote_id, button_id)
                await button_history.increment(button_action)
                asyncio.ensure_future(
                    self.shutdown_latch_wrapper.wrap_with_shutdown_latch(
                        button_watcher_loop(button_history)
                    )
                )
            else:
                await button_history.increment(button_action)
            self.button_histories_by_remote_id[remote_id] = button_history
