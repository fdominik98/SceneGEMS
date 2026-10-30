"""Job types: one module per JobType, each with its payload model and runner.

job_runner.py                 run_job(job, node, report): the node daemon's entry point
job_types.py                  job type to module
job_payload.py                shared payload pieces and payload parsing
pool_client.py                waiting on a pooled service (heartbeat, reply)
runner_container.py           running a job in one runner container
scene_generation_job.py       scene_generation, on the scene generation pool
trajectory_generation_job.py  trajectory_generation, on the trajectory generation pool
simulation_job.py             simulation, by the runner its payload names (simulation_runners/: kinematic, ardupilot)
monitoring_post_hoc_job.py    monitoring.post_hoc, in a monitoring container
calibration_deviation_job.py  calibration.deviation, in a scenario execution container
in_container/                 the entry point inside a runner container
"""
