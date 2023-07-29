from __future__ import annotations
from contextlib import asynccontextmanager
import logging
from typing import Optional
from caseta_to_mqtt.asynchronous.mutex_wrapper import MutexWrapped

from caseta_to_mqtt.z2m.model import GroupState, Zigbee2mqttGroup


LOGGER = logging.getLogger(__name__)


class AllGroups:
    def __init__(self) -> None:
        self._groups: MutexWrapped[set[Zigbee2mqttGroup]] = MutexWrapped(set())

    async def update_groups(self, new_groups: set[Zigbee2mqttGroup]):
        async with self._groups.get() as current_groups:
            removed_groups = current_groups.value.difference(new_groups)
            added_groups = new_groups.difference(current_groups.value)
            unchanged_groups = new_groups.intersection(current_groups.value)
            LOGGER.debug(
                "%s removed groups, %s added groups, %s unchanged groups",
                len(removed_groups),
                len(added_groups),
                len(unchanged_groups),
            )
            current_groups.value = added_groups.union(unchanged_groups)

    async def get_groups(self) -> set[Zigbee2mqttGroup]:
        """N.B. don't modify the groups that you get returned here"""
        async with self._groups.get() as groups:
            return groups.value


class GroupStateManager:
    def __init__(self) -> None:
        # this is a wonky type: a mutex locked dict of mutex locked group state objects
        # - we want adding and removing keys to be concurrent-safe (no two tasks should make a new entry for
        #   the same key concurrently)
        # - we want updates to each value to be concurrent-safe (no two tasks should be updating or reading
        #   an entry concurrently)
        # - two different KV pairs can be individually updated concurrently
        # so the access pattern should look like:
        # async with "the lock on the dict of GroupState objects locked":
        #   ensure that a mutex-wrapped value for a given key exists. if it doesn't create one
        #   get the KV pair
        # async with "the lock on the KV pair acquired":
        #   make whatever updates to the value that you need
        #
        # this should ensure the concurrency behavior that I want.
        self.group_state: MutexWrapped[
            dict[str, MutexWrapped[Optional[GroupState]]]
        ] = MutexWrapped({})

    @asynccontextmanager
    async def get_group_state(self) -> dict[str, MutexWrapped[Optional[GroupState]]]:
        async with self.group_state.get() as locked_group_state_dict:
            yield locked_group_state_dict.value

    async def put_group_state(self, group_friendly_name: str, group_state: GroupState):
        async with self.group_state.get() as locked_group_state:
            current_group_state = locked_group_state.value.get(group_friendly_name)
            if not current_group_state:
                locked_group_state.value[group_friendly_name] = group_state
            else:
                updated_group_state = GroupState(
                    brightness=current_group_state.brightness or group_state.brightness,
                    state=group_state.state,
                    scene=current_group_state.scene or group_state.scene,
                    updated_at=group_state.updated_at,
                )
            locked_group_state.value[group_friendly_name] = updated_group_state
