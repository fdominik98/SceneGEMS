"""Artifact transport on the worker node (P4.3): job inputs from the control node, job results to it.

artifact_client.py  HTTP to the control node's artifact routes, the worker node naming itself in the worker node id header
artifact_cache.py   a bounded, hash-checked cache in the worker node's state volume
worker_node_artifacts.py   load and store as the job runner calls them (cluster/worker_node/jobs/job_runner.py)
"""
