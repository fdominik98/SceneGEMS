import pytest

from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import ObservationControl, format_frame_line, format_status_line, parse_frame_line, parse_status_line


def test_status_lines_round_trip():
    assert parse_status_line(format_status_line("monitored 100 of 200 scenes", 0.5)) == ("monitored 100 of 200 scenes", 0.5)
    assert parse_status_line(format_status_line("started")) == ("started", None)


def test_other_lines_are_log_lines():
    assert parse_status_line("Traceback (most recent call last):") is None
    assert parse_status_line("scenegems-status not json") is None


def test_observation_requests_round_trip_and_partial_documents_are_refused():
    control = ObservationControl(active=True, speed=12.5, revision=4)
    assert ObservationControl.from_document(control.to_document()) == control
    assert ObservationControl() == ObservationControl(active=False, speed=1.0, revision=0)
    for text in ('{"active": true, "spe', "[]", '{"active": true, "speed": 0, "revision": 1}', '{"active": true, "revision": 1}', ""):
        with pytest.raises(ValueError):
            ObservationControl.from_document(text)


def test_frame_lines_carry_one_json_object():
    assert parse_frame_line(format_frame_line('{"timestamp": 3}')) == {"timestamp": 3}
    assert parse_frame_line(format_frame_line("[1, 2]")) is None
    assert parse_frame_line(format_frame_line("{broken")) is None
    assert parse_frame_line("frame {}") is None
    assert parse_status_line(format_frame_line("{}")) is None and parse_frame_line(format_status_line("x")) is None


def test_a_status_line_may_carry_a_detail():
    from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import format_status_line, parse_status

    line = format_status_line("ready to start", None, {"phase": "ready_to_start"})
    assert parse_status(line) == ("ready to start", None, {"phase": "ready_to_start"})
    assert parse_status(format_status_line("running", 0.5)) == ("running", 0.5, None), "no detail unless the job gives one"
    assert parse_status('scenegems-status {"message": "odd", "detail": "not an object"}') == ("odd", None, None)
    assert parse_status("a log line") is None and parse_status("scenegems-status not json") is None


def test_the_request_document_carries_the_operators_start():
    from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import ObservationControl

    assert not ObservationControl().started
    started = ObservationControl(active=True, speed=5.0, revision=3, started=True)
    assert ObservationControl.from_document(started.to_document()) == started
    assert not ObservationControl.from_document('{"active": true, "speed": 5.0, "revision": 2}').started, "a document of before the start"
