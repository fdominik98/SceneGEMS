"""Pooled services: one long-lived container per subsystem and worker node, with a worker pool sized by slots.

pooled_service.py              the shared lifecycle and compose layout
design_space_exploration_pool.py  design space exploration service
scene_generation_pool.py       scene generation service
trajectory_generation_pool.py  trajectory generation service
monitoring_pool.py             monitoring service
service_pools.py               a worker node's pools, started with the daemon and started again when one is gone
"""
