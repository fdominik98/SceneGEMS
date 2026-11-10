"""Paths and headers of the control node's cluster API, shared by control node and worker node.

The worker node reaches the control node over plain HTTP and WebSocket: every machine on the VPN is
trusted, so there is no pairing, no credential and no TLS. A worker node names itself in its Hello
and, on the artifact routes, in the WORKER_NODE_ID_HEADER.
"""

WORKER_NODE_CONTROL_PATH = "/cluster/worker-node/control"  # WebSocket opened by the worker node, frames from messages.py
JOBS_PATH = "/cluster/jobs"  # POST JobSubmission; GET lists jobs, GET <JOBS_PATH>/<job id> one job
# GET and PUT <ARTIFACTS_PATH>/<sha256> on the worker node API (WORKER_NODE_ID_HEADER); GET and HEAD <ARTIFACTS_PATH>/<sha256> and POST <ARTIFACTS_PATH>?kind= (the operator's upload) on the operator API
ARTIFACTS_PATH = "/cluster/artifacts"
# operator API (campaign_routes.py): POST a campaign config; GET lists campaigns; GET and DELETE <CAMPAIGNS_PATH>/<campaign id> read and delete one;
# GET <CAMPAIGNS_PATH>/<campaign id>/outputs?step= and /findings?step= read a step's outputs and summary
CAMPAIGNS_PATH = "/cluster/campaigns"
LIVE_PATH = "/cluster/live"  # operator API: the browser's live channel WebSocket (live.py)

CATALOG_PATH = "/cluster/catalog"  # operator API: GET <CATALOG_PATH>/classes the class catalog, GET <CATALOG_PATH>/stacks what a campaign run may use (catalog_routes.py)
DOMAIN_PATH = "/cluster/domain"  # operator API: GET and POST the cluster's domain configuration (setting_routes.py)
CAMPAIGN_PRESETS_PATH = "/cluster/campaign-presets"  # operator API: GET the presets, POST one to save, DELETE <CAMPAIGN_PRESETS_PATH>/<preset id> (setting_routes.py)

WORKER_NODE_ID_HEADER = "X-Worker-Node-Id"  # the worker node's id on the artifact routes; on the control socket the Hello names it
