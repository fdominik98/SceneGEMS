from datetime import datetime, timezone

from scenegems_tool.cluster.control_node import job_activity
from scenegems_tool.cluster.control_node.job_activity import JobActivity
from scenegems_tool.cluster.protocol.messages import JobStatus, LogLine, LogLines, LogStream
from tests.scenegems_tool.persistence.stores.builders import ManualClock

AT = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def _lines(job_id: str, texts) -> LogLines:
    return LogLines(lease_id="lease", job_id=job_id, lines=[LogLine(timestamp=AT, stream=LogStream.STDOUT, source="runner", text=text) for text in texts])


def test_latest_status_wins():
    clock = ManualClock()
    activity = JobActivity(clock)
    activity.status(JobStatus(lease_id="lease", job_id="job", progress=0.2, message="starting"))
    clock.advance(3)
    activity.status(JobStatus(lease_id="lease", job_id="job", progress=0.5, message="halfway"))
    progress = activity.progress("job")
    assert (progress.progress, progress.message, progress.at) == (0.5, "halfway", clock.now)
    assert activity.progress("other") is None


def test_log_lines_are_bounded_per_job():
    activity = JobActivity()
    activity.logs(_lines("job", [str(index) for index in range(job_activity.MAX_LINES_PER_JOB + 5)]))
    lines = activity.lines("job")
    assert len(lines) == job_activity.MAX_LINES_PER_JOB and lines[0].text == "5"
    assert activity.lines("other") == []


def test_the_least_recently_active_jobs_are_dropped(monkeypatch):
    monkeypatch.setattr(job_activity, "MAX_JOBS", 2)
    activity = JobActivity()
    for job_id in ("a", "b"):
        activity.logs(_lines(job_id, ["x"]))
    activity.logs(_lines("a", ["y"]))
    activity.logs(_lines("c", ["z"]))
    assert activity.lines("b") == [] and [line.text for line in activity.lines("a")] == ["x", "y"]
