"""Pooled services: one long-lived Deployment per subsystem and worker node, with a worker pool sized by slots.

pooled_service.py              the shared lifecycle and the Deployment
design_space_exploration_pool.py  design space exploration service
scene_generation_pool.py       scene generation service
trajectory_generation_pool.py  trajectory generation service
monitoring_pool.py             monitoring service
simulation_pool.py             simulation service, which starts the runs of its tasks
service_pools.py               a worker node's pools, started after the Welcome and applied again when one's Deployment is gone
"""
