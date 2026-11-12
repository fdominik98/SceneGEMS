"""Per-job stacks: the containers of one job, an instance in the worker node's compose project, created for the job and removed after it.

job_stack.py                 run a job's stack to completion: runner plus the services it needs
job_container_io.py          how the runner container receives its job and returns its result
"""
