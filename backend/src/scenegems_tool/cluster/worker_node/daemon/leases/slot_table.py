"""Slot accounting: how many jobs of each type the worker node runs at once.

A slot is taken when the worker node accepts a lease and given back when the job's worker has
stopped and its containers are gone, so a slot count is never exceeded on the machine,
not even while a cancelled job is still being torn down.

A job may take slots of more than one type: a simulation that is judged while it runs takes a
monitoring slot beside its simulation slot (cluster/fingerprints/components.py slot_job_types).
Its slots are taken together or not at all (take_all) and given back together (give_back_all).
"""

import threading
from typing import Dict, Iterable, Optional

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.worker_node_description import SlotUsage


class SlotTable:
    def __init__(self, slots: Dict[JobType, int]):
        if any(count < 1 for count in slots.values()):
            raise ValueError(f"Every job type needs at least one slot: {slots}")
        self._slots = dict(slots)
        self._in_use: Dict[JobType, int] = {job_type: 0 for job_type in slots}
        self._lock = threading.Lock()

    @property
    def capacity(self) -> Dict[JobType, int]:
        return dict(self._slots)

    def offers(self, job_type: JobType) -> bool:
        return job_type in self._slots

    def try_take(self, job_type: JobType) -> bool:
        """Take one slot of the job type; False when the worker node offers none or all are in use."""
        with self._lock:
            if job_type not in self._slots or self._in_use[job_type] >= self._slots[job_type]:
                return False
            self._in_use[job_type] += 1
            return True

    def take_all(self, job_types: Iterable[JobType]) -> Optional[JobType]:
        """Take one slot of each of the job types, or none of them. None when all were taken, else the first type the worker node offers none of or has none free."""
        wanted = list(job_types)
        with self._lock:
            for job_type in wanted:
                if job_type not in self._slots or self._in_use[job_type] >= self._slots[job_type]:
                    return job_type
            for job_type in wanted:
                self._in_use[job_type] += 1
            return None

    def give_back_all(self, job_types: Iterable[JobType]) -> None:
        for job_type in job_types:
            self.give_back(job_type)

    def give_back(self, job_type: JobType) -> None:
        with self._lock:
            if self._in_use.get(job_type, 0) <= 0:
                raise ValueError(f"No {job_type.value} slot is in use")
            self._in_use[job_type] -= 1

    def free(self, job_type: JobType) -> int:
        with self._lock:
            return self._slots.get(job_type, 0) - self._in_use.get(job_type, 0)

    def in_use(self) -> SlotUsage:
        with self._lock:
            return {job_type: count for job_type, count in self._in_use.items() if count}
