"""
SceneGEMS tool: the runtime that executes assurance workflows.

The package tree is a map. Depth follows concreteness: a package at depth 1 names an
abstract concept of the architecture, and each level below it is a more concrete concept.
See system_revision/architecture_design.md for the full design.

Present now:
    gateway/        browser WebSocket API: app, protocol, serialization, per-connection sessions
    workbench/      single-machine demo orchestration kept working through the revision
    messaging/      MQTT clients and services that carry subsystem traffic
    subsystems/     one package per subsystem
        scene_generation/, trajectory_generation/, monitoring/, scenario_execution/
    vessel_stack/   ASV software, control layer and simulation layer as adapters, each layer in its own container
        contracts/              roles, ports, capabilities, adapter specs, clock, stack config, the wire protocol
                                between a stack's containers (lockstep_wire.py) and their names (stack_services.py)
        registry/               adapter registry, resolver, measured capability data
        simulation_layers/      kinematic/ (one simulator container per scenario), gazebo/ (generators), ardupilot_sim/
        control_layers/         ardupilot/ (SITL per vessel), custom/ (a controller container per vessel)
        asv_software/           replay/ and usv_navigation/ (a container per vessel; USV Navigation in its own image),
                                mission_planner/ (specs)
        hosting.py              where a run's layers are: the stack's containers, or the caller's process (tests, calibration)
    cluster/        distributed integration layer
        protocol/               typed, versioned control node to worker node messages and jobs
        worker_node/                   instance scopes, launchers, job types and the worker node daemon
        fingerprints/           image build fingerprints: label reader, comparison, images per job type
        release/                the release bundle a deployment tool installs: images, stacks, roles
        control_node/                 worker node registry, scheduler, lease manager and the control node's API and process
    architecture/   the architecture description: documents built from the specs in code, written to
                    backend/assets/architecture at control node startup and served to the web console's Capabilities page
    persistence/    the control node's Postgres: tables, migrations, worker node, job, campaign, result and artifact record stores
    assurance/      campaigns over the functional scenario catalog
        campaign/               config model, YAML, hash and seeds; class catalog; validation

Planned (added by later phases):
    assurance/pipeline/         the pipeline engine that runs a campaign's cases (P4.4)
    persistence/artifacts/      the content-addressed artifact store (P4.3)
    vessel_stack/adapters/      shared edges between layers (mavlink, gz_transport)
"""

__all__: list[str] = []
