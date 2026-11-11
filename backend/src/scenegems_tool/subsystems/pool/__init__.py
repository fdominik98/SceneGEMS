"""What every subsystem has in common: requests become tasks, tasks wait in a queue and run in a pool.

    pool_task.py          a task, its states, and what its worker process gets to talk back
    task_pool.py          the queue and the pool: at most as many running tasks as the pool is large
    pool_service_main.py  the loop of a subsystem's container

The MQTT side is in messaging/mqtt_pool_service.py (the subsystem) and messaging/mqtt_pool_client.py
(whoever sends it requests: the worker node daemon).
"""
