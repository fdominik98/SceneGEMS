"""Pooled services: one long-lived container per subsystem and worker node, with a worker pool sized by slots.

pooled_service.py              the shared lifecycle and compose layout
scene_generation_pool.py       scene generation service
trajectory_generation_pool.py  trajectory generation service
monitor_service.py             live COLREGS monitor
service_pools.py               a worker node's pools, started on first use
"""
