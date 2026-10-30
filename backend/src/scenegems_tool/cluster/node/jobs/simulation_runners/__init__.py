"""The runners of the simulation job (simulation_job.py), one module per runner.

kinematic_runner.py  runner kinematic: replay or USV Navigation on the kinematic layer, in a scenario execution container
ardupilot_runner.py  runner ardupilot: replay over the lockstep MAVLink adapter, on a SITL or Gazebo stack per job

Each runner module defines its payload model (PAYLOAD_MODEL, with runner as a Literal), the vessel
stacks a payload runs (vessel_stacks), `run` (the node's part, given the parsed payload) and
`execute` (the in-container part). A new runner adds a module here, its name to
cluster/fingerprints/components.py (SimulationRunner, RUNNER_STACKS), its module to
simulation_job.RUNNER_MODULES and its payload model to simulation_job.RunnerPayload; a campaign
stack it runs also needs its vessel stacks in assurance/campaign/config_validation.vessel_stacks
and in the console's domain/cluster/components.ts runStackComponents.
"""
