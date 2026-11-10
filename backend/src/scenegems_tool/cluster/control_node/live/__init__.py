"""The control node's live channel to browsers (cluster/protocol/live.py is the contract).

live_channel.py      connections, reference counted subscriptions, bounded outboxes, rate limits
topics.py            producers of the worker nodes, job and campaign topics; create_live_channel wires them
observation_hub.py   instance topics: pool previews from the cluster broker, job status, simulation frames
"""
