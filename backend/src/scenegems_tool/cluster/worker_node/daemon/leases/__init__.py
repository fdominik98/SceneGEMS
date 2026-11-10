"""Leases: the jobs the control node granted this worker node, each run by its own worker thread within the slots.

slot_table.py      slots per job type, taken at accept and given back when the job's containers are gone
lease.py           one lease's state machine: running, finished, cancelling, lost, releasing, ended
report_batcher.py  report calls to JobStatus and LogLines frames, batched and rate limited
lease_worker.py    the worker thread: run_job, then the JobResult
lease_manager.py   offers, renewals, cancel, drain, results and shutdown
"""
