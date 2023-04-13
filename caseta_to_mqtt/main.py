import asyncio
from asyncio.locks import Lock
from datetime import datetime, timedelta
from enum import Enum
import itertools
import logging
import os
import sys
from typing import Callable, Optional
from pylutron_caseta.smartbridge import Smartbridge

LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(LOGLEVEL)
LOGGER.addHandler(logging.StreamHandler(stream=sys.stderr))

PATH_TO_CERT_FILE: str = "/Users/dan/.config/pylutron_caseta/caseta.run.crt"
PATH_TO_KEY_FILE: str = "/Users/dan/.config/pylutron_caseta/caseta.run.key"
PATH_TO_CA_FILE: str = "/Users/dan/.config/pylutron_caseta/caseta.run-bridge.crt"
CASETA_BRIDGE_HOSTNAME = "caseta.run"

DOUBLE_CLICK_WINDOW = timedelta(milliseconds=500)
BUTTON_WATCHER_SLEEP_DURATION = timedelta(milliseconds=250)
BUTTON_WATCHER_MAX_DURATION = timedelta(seconds=5)


class IllegalStateTransitionError(Exception):
    """Raised when an out-of-order button state transition is requested"""

    pass


class ButtonId(Enum):
    POWER_ON = 0
    FAVORITE = 1
    POWER_OFF = 2
    INCREASE = 3
    DECREASE = 4

    @classmethod
    def of_int(cls, value: int):
        return {member.value: member for member in cls}[value]


class ButtonAction(Enum):
    PRESS = 0
    RELEASE = 1

    @classmethod
    def of_str(cls, value: str):
        return {member.name: member for member in cls}[value.upper()]


class ButtonState(Enum):
    NOT_PRESSED = 0
    FIRST_PRESS_AWAITING_RELEASE = 1
    FIRST_PRESS_AND_FIRST_RELEASE = 2
    SECOND_PRESS_AWAITING_RELEASE = 3
    DOUBLE_PRESS_FINISHED = 4

    def next_state(self):
        if self == ButtonState.DOUBLE_PRESS_FINISHED:
            raise IllegalStateTransitionError(
                "there is no state after finishing a double press"
            )
        return list(ButtonState)[self.value + 1]

    @property
    def is_awaiting_press(self):
        return self in {
            ButtonState.NOT_PRESSED,
            ButtonState.FIRST_PRESS_AND_FIRST_RELEASE,
        }

    @property
    def is_awaiting_release(self):
        return self in {
            ButtonState.FIRST_PRESS_AWAITING_RELEASE,
            ButtonState.SECOND_PRESS_AWAITING_RELEASE,
        }


class ButtonHistory:
    def __init__(self, remote_id: str, button_id: str) -> None:
        self.remote_id: str = remote_id
        self.button_id: str = button_id
        self.button_state: ButtonState = ButtonState.NOT_PRESSED
        self.tracking_started_at: Optional[datetime] = None
        self.is_finished: bool = False
        self.mutex: Lock = Lock()

    async def increment(self, button_action: ButtonAction):
        async with self.mutex:
            self._validate_button_state_transition(button_action)
            if self.button_state == ButtonState.NOT_PRESSED:
                self.tracking_started_at = datetime.now()
            self.button_state = self.button_state.next_state()

    def _validate_button_state_transition(self, button_action: ButtonAction) -> None:
        if button_action == ButtonAction.PRESS:
            if not self.button_state.is_awaiting_press:
                raise IllegalStateTransitionError()
        elif button_action == ButtonAction.RELEASE:
            if not self.button_state.is_awaiting_release:
                raise IllegalStateTransitionError

    @property
    def is_timed_out(self) -> bool:
        return (
            self.tracking_started_at
            and (datetime.now() - self.tracking_started_at)
            > BUTTON_WATCHER_MAX_DURATION
        )


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
    def __init__(self, shutdown_latch: asyncio.Condition):
        self.mutex = Lock()
        self.shutdown_latch: asyncio.Condition = shutdown_latch
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
                    self._notify_if_exception(button_watcher_loop(button_history))
                )
            else:
                await button_history.increment(button_action)
            self.button_histories_by_remote_id[remote_id] = button_history

    async def _notify_if_exception(self, future: asyncio.Future):
        try:
            await future
        except Exception as e:
            LOGGER.error(
                f"encountered an exception: {e}. starting to shutdown.", exc_info=True
            )
            async with self.shutdown_latch:
                self.shutdown_latch.notify()


async def main_loop():
    shutdown_latch = asyncio.Condition()

    bridge = Smartbridge.create_tls(
        CASETA_BRIDGE_HOSTNAME, PATH_TO_KEY_FILE, PATH_TO_CERT_FILE, PATH_TO_CA_FILE
    )

    await bridge.connect()
    button_tracker = ButtonTracker(shutdown_latch)

    all_buttons = bridge.get_buttons()
    buttons_by_remote_id = {
        remote_id: list(remote_buttons)
        for remote_id, remote_buttons in itertools.groupby(
            all_buttons.values(), lambda button: button["parent_device"]
        )
    }

    for remote_id, buttons in buttons_by_remote_id.items():
        [
            bridge.add_button_subscriber(
                button["device_id"],
                button_tracker.button_event_callback(
                    remote_id, ButtonId.of_int(button["button_number"])
                ),
            )
            for button in buttons
        ]

    async with shutdown_latch:
        await shutdown_latch.wait()
        LOGGER.info("received shutdown signal. shutting down")
        await bridge.close()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    main_task = loop.create_task(main_loop())
    loop.run_until_complete(main_task)
