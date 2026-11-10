"""The control connection to the control node.

control_link.py        one WebSocket: TLS against the CA, bearer credential, thread-safe send
reconnect_backoff.py   waits between connection attempts
status_frames.py       Hello and Heartbeat from the worker node's state
"""
