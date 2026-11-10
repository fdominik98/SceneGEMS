"""The machine's resources as the worker node reports them: CPUs, memory, free memory, free disk and load.

Read inside the daemon's container from /proc, which shows the host's values. The daemon's
own cgroup limits are deliberately not applied: jobs run in sibling containers outside
that cgroup, so the host is what they share. Free disk is measured on the runtime assets
volume, which lives on Docker's disk like the job containers and images. Where /proc is
missing (a development run on Windows or macOS) psutil is used when it is installed.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from scenegems_tool.cluster.protocol.worker_node_description import WorkerNodeResources

_MIB = 1024 * 1024


@dataclass
class ResourceProbe:
    disk_path: Path  # a folder on the disk the jobs use
    proc_root: Path = field(default=Path("/proc"))

    def read(self) -> WorkerNodeResources:
        cpus = self._cpus()
        memory_mb, free_memory_mb = self._memory_mb()
        return WorkerNodeResources(
            cpus=float(cpus),
            memory_mb=memory_mb,
            free_memory_mb=free_memory_mb,
            free_disk_mb=self._free_disk_mb(),
            load_average=round(self._load() / cpus, 4) if cpus else 0.0,
        )

    def _cpus(self) -> int:
        stat = _read(self.proc_root / "stat")
        if stat is not None:
            count = sum(1 for line in stat.splitlines() if line.startswith("cpu") and line[3:4].isdigit())
            if count:
                return count
        return os.cpu_count() or 1

    def _memory_mb(self) -> tuple:
        meminfo = _read(self.proc_root / "meminfo")
        if meminfo is not None:
            values = _meminfo_kib(meminfo)
            total = values.get("MemTotal", 0)
            available = values.get("MemAvailable", values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0))
            return total // 1024, min(available, total) // 1024
        psutil = _psutil()
        if psutil is not None:
            memory = psutil.virtual_memory()
            return memory.total // _MIB, memory.available // _MIB
        return 0, 0

    def _load(self) -> float:
        loadavg = _read(self.proc_root / "loadavg")
        if loadavg is not None:
            try:
                return float(loadavg.split()[0])
            except (IndexError, ValueError):
                return 0.0
        try:
            return os.getloadavg()[0]
        except (AttributeError, OSError):
            return 0.0

    def _free_disk_mb(self) -> int:
        path = Path(self.disk_path)
        while not path.exists() and path != path.parent:
            path = path.parent
        try:
            return shutil.disk_usage(path).free // _MIB
        except OSError:
            return 0


def _meminfo_kib(text: str) -> Dict[str, int]:
    values: Dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[name.strip()] = int(parts[0])
    return values


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None


def _psutil():
    try:
        import psutil
    except ImportError:
        return None
    return psutil
