"""The node daemon: one per node instance, in its own container, connected to one master.

It needs no master to start and no pairing: it dials its master, keeps retrying until that is up,
keeps a WebSocket to it, leases jobs within its slots and runs each one through jobs/run_job in
the job's subsystem container. It never runs simulation or generation code itself.

    configuration/   environment and .env: master address, slots, components, state folder
    control/         the control WebSocket, reconnect backoff, Hello and Heartbeat
    leases/          slot accounting, the lease state machine, workers, report batching
    resource_probe.py  CPUs, memory, disk and load as the node reports them
    node_runtime.py    the NodeContext run_job gets: the master's plain broker, leftovers
    node_daemon.py     start-up order and the connection loop
    __main__.py        the container's entry point and exit codes
"""
