"""Typed, versioned messages between the control node and its worker nodes.

Both sides import these definitions, so control node and worker node cannot drift apart silently.

    version.py           PROTOCOL_VERSION and the mismatch error
    model_base.py        immutable models; frames carry the protocol version
    jobs.py              job types, states, requirements, submission and the leased job
    artifacts.py         artifact references in payloads and results, declared artifact fields
    worker_node_description.py  slot offers, resources
    messages.py          WebSocket frames, worker node to control node and control node to worker node
    codec.py             encode and decode frames, version checked first
    routes.py            HTTP paths and the worker node id header of the control node's cluster API
    live.py              the browser's live channel on the operator API: messages and topics
"""
