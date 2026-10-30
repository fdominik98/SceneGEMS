"""JSON views of jobs and nodes for the operator API."""

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from scenegems_tool.cluster.fingerprints.components import component_images, is_component, ordered
from scenegems_tool.cluster.master.job_activity import JobProgress
from scenegems_tool.cluster.master.registry.node_session import NodeSession
from scenegems_tool.persistence.stores import JobEventRecord, JobRecord, NodeRecord


def job_view(job: JobRecord, progress: Optional[JobProgress] = None) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "job_type": job.job_type.value,
        "state": job.state.value,
        "priority": job.priority,
        "attempt": job.attempt,
        "failed_attempts": job.failed_attempts,
        "max_attempts": job.max_attempts,
        "idempotency_key": job.idempotency_key,
        "requirements": job.requirements.model_dump(),
        "allowed_nodes": list(job.allowed_nodes),
        "lease_owner": job.lease_owner,
        "lease_expires_at": job.lease_expires_at,
        "submitted_at": job.submitted_at,
        "available_at": job.available_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "result": job.result,
        "error": job.error,
        "progress": None if progress is None else asdict(progress),
    }


def job_detail_view(job: JobRecord, progress: Optional[JobProgress], events: List[JobEventRecord], log_lines: List[Any]) -> Dict[str, Any]:
    view = job_view(job, progress)
    view["payload"] = job.payload
    view["events"] = [
        {
            "at": event.at,
            "kind": event.kind.value,
            "from_state": None if event.from_state is None else event.from_state.value,
            "to_state": event.to_state.value,
            "attempt": event.attempt,
            "lease_id": event.lease_id,
            "node_id": event.node_id,
            "detail": event.detail,
        }
        for event in events
    ]
    view["log_lines"] = [line.model_dump(mode="json") for line in log_lines]
    return view


def component_views(node: NodeRecord, session: Optional[NodeSession]) -> List[Dict[str, Any]]:
    """Each component the node offers, in catalog order: its images and state, out_of_date while one of its images differs from the release."""
    catalog = component_images()
    stale = session.stale_components if session is not None else frozenset()
    known = [component for component in node.components if is_component(component)]
    components = list(ordered(known)) + sorted(component for component in node.components if not is_component(component))
    return [{"component": component, "images": list(catalog.get(component, ())), "state": "out_of_date" if component in stale else "usable"} for component in components]


def node_view(node: NodeRecord, session: Optional[NodeSession]) -> Dict[str, Any]:
    return {
        "node_id": node.node_id,
        "name": node.name,
        "status": node.status.value,
        "connected": session is not None,
        "out_of_date": bool(session and session.out_of_date),  # some component's images differ from the release
        "fingerprint_mismatches": [asdict(mismatch) for mismatch in session.out_of_date] if session else [],
        "software_revision": node.software_revision,
        "machine": node.machine,
        "labels": node.labels,
        "resources": node.resources.model_dump(),
        "slots": {job_type.value: {"slots": usage.slots, "slots_in_use": usage.slots_in_use} for job_type, usage in node.slots.items()},
        "components": component_views(node, session),
        "leases": sorted(session.leases) if session else [],
        "registered_at": node.registered_at,
        "last_seen_at": node.last_seen_at,
    }
