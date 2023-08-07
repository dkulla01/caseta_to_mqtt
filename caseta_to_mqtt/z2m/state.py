from __future__ import annotations
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import logging
from typing import AsyncGenerator, Optional

from dynaconf import Dynaconf
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
    def __init__(self, settings: Dynaconf) -> None:
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

        self._settings: Dynaconf = settings
        self._zigbee2mqtt_group_scene_cache_ttl = timedelta(
            seconds=settings.zigbee2mqtt_group_scene_cache_ttl_seconds
        )

    @asynccontextmanager
    async def get_group_states_by_friendly_name(
        self,
    ) -> AsyncGenerator[dict[str, MutexWrapped[Optional[GroupState]]], None]:
        async with self.group_state.get() as locked_group_state_dict:
            yield locked_group_state_dict.value

    async def get_group_state(
        self, friendly_name: str
    ) -> Optional[MutexWrapped[Optional[GroupState]]]:
        async with self.group_state.get() as locked_group_state_dict:
            return locked_group_state_dict.value.get(friendly_name)

    def _is_saved_group_state_scene_too_old(
        self, current_time: datetime, z2m_group_state: GroupState
    ) -> bool:
        saved_group_state_age = current_time - z2m_group_state.updated_at
        return saved_group_state_age > self._zigbee2mqtt_group_scene_cache_ttl

    async def update_group_state(
        self, z2m_group_name: str, new_group_state: GroupState
    ):
        # ensure a record tracking the group exists
        now = datetime.now()
        current_group_state: MutexWrapped[Optional[GroupState]]
        async with self.group_state.get() as locked_group_state_dict:
            if z2m_group_name not in locked_group_state_dict.value:
                locked_group_state_dict.value[z2m_group_name] = MutexWrapped(None)
            current_group_state = locked_group_state_dict.value[z2m_group_name]

        # now that we have a record tracking the z2m group, merge the new group state
        # value into the existing group state value
        #
        # what are the chances that I got this update logic right?
        async with current_group_state.get() as locked_group_state:
            if not locked_group_state.value:
                locked_group_state.value = GroupState(
                    brightness=new_group_state.brightness,
                    state=new_group_state.state,
                    scene=None,
                    updated_at=now,
                )

            if self._is_saved_group_state_scene_too_old(now, locked_group_state.value):
                locked_group_state.value = GroupState(
                    brightness=locked_group_state.value.brightness,
                    state=locked_group_state.value.state,
                    scene=None,
                    updated_at=now,
                )
            locked_group_state.value = GroupState(
                brightness=new_group_state.brightness
                or locked_group_state.value.brightness,
                state=new_group_state.state or locked_group_state.value.state,
                scene=new_group_state.scene or locked_group_state.value.scene,
                updated_at=now,
            )
