"""The worker node integration layer: everything that runs subsystem instances on one machine.

    instance_scope.py   instance identity and the names derived from it (containers, projects, labels)
    subsystem.py        the subsystems and their images
    worker_node_context.py     what a job needs from its worker node: identity, slots, broker, pools
    job_report.py       status and log lines of a running job, and its failure
    launchers/          start and stop subsystem containers
    jobs/               one module per job type and run_job, the daemon's entry point
    daemon/             the worker node daemon: the control connection to the control node, leases

Only a worker node runs the launchers, its daemon for the pools and its simulation subsystem for the stack of a run: the control node starts no containers.
"""
