from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class IllegalStateTransitionError(Exception):
    """Raised when an out-of-order button state transition is requested"""

    pass


@dataclass(frozen=True)
class PicoRemote:
    device_id: int
    name: str
    buttons_by_button_id: dict[int, ButtonId]


@dataclass(frozen=True)
class PicoTwoButton(PicoRemote):
    TYPE: ClassVar[str] = "Pico2Button"


@dataclass(frozen=True)
class PicoThreeButtonRaiseLower(PicoRemote):
    TYPE: ClassVar[str] = "Pico3ButtonRaiseLower"


class ButtonId(Enum):
    """
    these button numbers are consistent for both Pico3ButtonRaiseLower and Pico2Button remotes
    """

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

    def is_button_action_valid(self, button_action: ButtonAction) -> bool:
        return (self.is_awaiting_press and button_action == ButtonAction.PRESS) or (
            self.is_awaiting_release and button_action == ButtonAction.RELEASE
        )

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
