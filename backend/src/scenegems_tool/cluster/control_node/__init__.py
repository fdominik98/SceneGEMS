"""The control node integration layer's control plane: it knows the worker nodes, leases them jobs and serves the control node's API.

Worker nodes connect to the control node (outbound only) over one authenticated WebSocket each; the
control node offers them queued jobs from its Postgres job store and keeps each lease alive
while the worker node renews it. State is in the database (persistence/), so a control node restart
loses only what the worker nodes resend on reconnect.

    timing.py           heartbeat, lease, offer and sweep periods, and why they are what they are
    control_plane.py    registry, scheduler and lease manager wired on one event loop, with timers
    job_activity.py     latest status and log lines of running jobs, in memory
    registry/           connected worker nodes and their status
        worker_node_session.py           one connected worker node: socket, latest facts, leases it holds
        worker_node_registry.py          sessions, heartbeats, drain, silent worker nodes offline
        lease_reconciliation.py   a reconnected worker node's running leases against the store's
    scheduling/         which worker node gets which job
        scheduler.py              round robin offers to eligible worker nodes through the store's claim
        worker_node_eligibility.py       online, up to date, resource guard
        fingerprint_policy.py     the control node's expected fingerprints, required of jobs and worker nodes
        reject_backoff.py         a worker node that rejects a job does not get it again for a while
    leases/
        lease_manager.py          accept, renew, reject, release, result, expiry sweep, reconnect
    control_link/
        worker_node_control_socket.py    the worker node's WebSocket: Hello, frame loop
    api/                the HTTP side, one app per listener
        control_node_apps.py            worker node API (plain HTTP), operator (workbench and jobs)
        worker_node_routes.py            control WebSocket
        operator_routes.py        jobs and worker nodes
        views.py                  JSON views of jobs and worker nodes
    settings.py         environment settings of the control node process
    server.py           the control node process: two listeners in one event loop (`python -m scenegems_tool.cluster.control_node`)
"""
