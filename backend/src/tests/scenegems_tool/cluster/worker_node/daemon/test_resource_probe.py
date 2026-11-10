"""The resource probe on a fake /proc, as the daemon's Linux container sees it."""

import shutil

from scenegems_tool.cluster.worker_node.daemon.resource_probe import ResourceProbe

STAT = "cpu  100 0 50 1000 0 0 0 0 0 0\ncpu0 25 0 12 250 0 0 0 0 0 0\ncpu1 25 0 13 250 0 0 0 0 0 0\ncpu2 25 0 12 250 0 0 0 0 0 0\ncpu3 25 0 13 250 0 0 0 0 0 0\nintr 0\nctxt 0\n"
MEMINFO = "MemTotal:       16384000 kB\nMemFree:         1024000 kB\nMemAvailable:    8192000 kB\nBuffers:          100000 kB\nCached:          2000000 kB\n"


def fake_proc(tmp_path, *, stat=STAT, meminfo=MEMINFO, loadavg="2.00 1.50 1.00 1/300 4000\n"):
    proc = tmp_path / "proc"
    proc.mkdir()
    for name, text in (("stat", stat), ("meminfo", meminfo), ("loadavg", loadavg)):
        if text is not None:
            (proc / name).write_text(text)
    return proc


def test_values_come_from_proc_and_the_disk(tmp_path):
    resources = ResourceProbe(disk_path=tmp_path, proc_root=fake_proc(tmp_path)).read()
    assert resources.cpus == 4.0
    assert resources.memory_mb == 16000 and resources.free_memory_mb == 8000
    assert resources.load_average == 0.5  # 2.0 over 4 CPUs
    assert abs(resources.free_disk_mb - shutil.disk_usage(tmp_path).free // (1024 * 1024)) <= 16


def test_an_older_kernel_without_memavailable_counts_free_buffers_and_cache(tmp_path):
    meminfo = "MemTotal:       16384000 kB\nMemFree:         1024000 kB\nBuffers:          1024000 kB\nCached:          2048000 kB\n"
    assert ResourceProbe(disk_path=tmp_path, proc_root=fake_proc(tmp_path, meminfo=meminfo)).read().free_memory_mb == 4000


def test_a_missing_disk_folder_is_measured_on_its_nearest_parent(tmp_path):
    resources = ResourceProbe(disk_path=tmp_path / "not" / "yet" / "created", proc_root=fake_proc(tmp_path)).read()
    assert resources.free_disk_mb > 0


def test_unreadable_values_fall_back_without_failing(tmp_path, monkeypatch):
    import scenegems_tool.cluster.worker_node.daemon.resource_probe as probe_module

    monkeypatch.setattr(probe_module, "_psutil", lambda: None)
    monkeypatch.setattr(probe_module.os, "cpu_count", lambda: 2)
    resources = ResourceProbe(disk_path=tmp_path, proc_root=fake_proc(tmp_path, stat=None, meminfo=None, loadavg="garbage")).read()
    assert resources.cpus == 2.0
    assert resources.memory_mb == 0 and resources.free_memory_mb == 0
    assert resources.load_average == 0.0


def test_without_proc_psutil_reports_memory(tmp_path):
    resources = ResourceProbe(disk_path=tmp_path, proc_root=tmp_path / "no-proc").read()
    assert resources.cpus >= 1
    assert resources.memory_mb > 0 and 0 < resources.free_memory_mb <= resources.memory_mb
