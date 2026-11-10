"""Per-job stacks: a compose project created for one job and removed after it.

job_stack.py                 run a job's stack to completion: runner plus the services it needs
job_container_io.py          how the runner container receives its job and returns its result
simulation_session_stack.py  the workbench's interactive simulation stack, one per session
"""
