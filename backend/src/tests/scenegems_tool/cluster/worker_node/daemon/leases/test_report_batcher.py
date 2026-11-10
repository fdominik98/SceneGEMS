from datetime import datetime, timezone

from scenegems_tool.cluster.protocol.messages import JobStatus, LogLines, LogStream
from scenegems_tool.cluster.worker_node.daemon.leases.report_batcher import DAEMON_SOURCE, MAX_LINE_CHARACTERS, ReportBatcher

INSTANT = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def batcher(clock: Clock, **options) -> ReportBatcher:
    return ReportBatcher("lease-1", "job-1", clock=clock, wall_clock=lambda: INSTANT, **options)


def lines(frames):
    return [line for frame in frames if isinstance(frame, LogLines) for line in frame.lines]


def test_status_is_coalesced_to_the_newest_within_the_interval():
    clock = Clock()
    report = batcher(clock, status_interval_s=0.5)
    report.status("starting", 0.0)
    [first] = report.take_frames()
    assert isinstance(first, JobStatus) and first.message == "starting" and first.progress == 0.0
    assert (first.lease_id, first.job_id) == ("lease-1", "job-1")
    report.status("step 1", 0.25)
    report.status("step 2", 0.5)
    clock.now = 0.4
    assert report.take_frames() == []
    clock.now = 0.5
    [second] = report.take_frames()
    assert second.message == "step 2" and second.progress == 0.5
    assert report.take_frames() == []  # nothing new


def test_force_sends_the_pending_status_at_once():
    clock = Clock()
    report = batcher(clock, status_interval_s=10.0)
    report.status("a")
    report.take_frames()
    report.status("done", 1.0)
    [status] = report.take_frames(force=True)
    assert status.message == "done"


def test_progress_is_clamped_into_the_unit_interval():
    report = batcher(Clock())
    report.status("over", 1.7)
    assert report.take_frames()[0].progress == 1.0


def test_log_lines_are_batched_into_frames_of_bounded_size():
    report = batcher(Clock(), max_lines_per_frame=3, burst_lines=100)
    for index in range(7):
        report.log("runner", f"line {index}", LogStream.STDERR if index % 2 else LogStream.STDOUT)
    frames = report.take_frames()
    assert [len(frame.lines) for frame in frames] == [3, 3, 1]
    assert [line.text for line in lines(frames)] == [f"line {index}" for index in range(7)]
    assert lines(frames)[1].stream == LogStream.STDERR and lines(frames)[0].source == "runner"
    assert lines(frames)[0].timestamp == INSTANT
    assert report.take_frames() == []


def test_lines_over_the_rate_are_dropped_and_counted():
    clock = Clock()
    report = batcher(clock, lines_per_second=10.0, burst_lines=5)
    for index in range(8):
        report.log("runner", f"line {index}")
    taken = lines(report.take_frames())
    assert [line.text for line in taken[:5]] == [f"line {index}" for index in range(5)]
    assert taken[5].stream == LogStream.DAEMON and taken[5].source == DAEMON_SOURCE
    assert "3 log lines dropped" in taken[5].text
    clock.now = 0.3  # three tokens refilled
    for index in range(4):
        report.log("runner", f"later {index}")
    taken = lines(report.take_frames())
    assert [line.text for line in taken[:3]] == ["later 0", "later 1", "later 2"]
    assert "1 log lines dropped" in taken[3].text


def test_daemon_lines_are_not_rate_limited():
    report = batcher(Clock(), lines_per_second=1.0, burst_lines=1)
    for index in range(4):
        report.daemon_line(f"note {index}")
    assert [line.text for line in lines(report.take_frames())] == [f"note {index}" for index in range(4)]


def test_a_full_buffer_keeps_the_newest_lines_and_says_so():
    report = batcher(Clock(), burst_lines=100, max_buffered_lines=4)
    for index in range(6):
        report.log("runner", f"line {index}")
    taken = lines(report.take_frames())
    assert [line.text for line in taken[:4]] == ["line 2", "line 3", "line 4", "line 5"]
    assert "2 older log lines dropped" in taken[-1].text


def test_long_lines_are_cut():
    report = batcher(Clock())
    report.log("runner", "x" * (MAX_LINE_CHARACTERS + 10))
    assert len(lines(report.take_frames())[0].text) == MAX_LINE_CHARACTERS
