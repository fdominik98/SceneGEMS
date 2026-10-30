"""Typed, versioned messages between the master and its nodes.

Both sides import these definitions, so master and node cannot drift apart silently.

    version.py           PROTOCOL_VERSION and the mismatch error
    model_base.py        immutable models; frames carry the protocol version
    jobs.py              job types, states, requirements, submission and the leased job
    artifacts.py         artifact references in payloads and results, declared artifact fields
    node_description.py  slot offers, resources
    messages.py          WebSocket frames, node to master and master to node
    codec.py             encode and decode frames, version checked first
    routes.py            HTTP paths and the node id header of the master's cluster API
    live.py              the browser's live channel on the operator API: messages and topics
"""
