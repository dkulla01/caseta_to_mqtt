from asyncio import Lock
from datetime import datetime
from enum import Enum
from typing import Optional

from caseta_to_mqtt.caseta import BUTTON_WATCHER_MAX_DURATION


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
