"""The worker node daemon: one per worker node instance, in its own container, connected to one control node.

It needs no control node to start and no pairing: it dials its control node, keeps retrying until that is up,
keeps a WebSocket to it, leases jobs within its slots and runs each one through jobs/run_job as
a request to the pool of the job's subsystem. It never runs simulation or generation code itself.

    configuration/   environment and .env: control node address, slots, components, state folder
    control/         the control WebSocket, reconnect backoff, Hello and Heartbeat
    leases/          slot accounting, the lease state machine, workers, report batching
    resource_probe.py  CPUs, memory, disk and load as the worker node reports them
    worker_node_runtime.py    the WorkerNodeContext run_job gets: the control node's plain broker, leftovers
    worker_node_daemon.py     start-up order and the connection loop
    __main__.py        the container's entry point and exit codes
"""
