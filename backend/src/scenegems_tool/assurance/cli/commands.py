"""The campaign commands: each takes the parsed arguments and a Session and prints to its output."""

import hashlib
import time
from argparse import Namespace
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TextIO

from scenegems_tool.assurance.cli.api_client import ApiError, OperatorApi
from scenegems_tool.assurance.cli.render import OUTPUT_HEADERS, campaign_row, campaign_summary, coverage_table, findings_summary, output_row, table
from scenegems_tool.cluster.protocol.routes import ARTIFACTS_PATH, CAMPAIGNS_PATH

FINAL_STATES = ("stopped", "completed")
FOLLOW_PAGE = 500


@dataclass
class Session:
    api: OperatorApi
    out: TextIO
    err: TextIO
    sleep: Callable[[float], None] = field(default=time.sleep)

    def say(self, text: str = "") -> None:
        print(text, file=self.out)


def campaign_path(campaign_id: str, suffix: str = "") -> str:
    return f"{CAMPAIGNS_PATH}/{campaign_id}{suffix}"


def create(session: Session, arguments: Namespace) -> int:
    path = Path(arguments.config)
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ApiError(None, [f"cannot read {path}: {error.strerror or error}"])
    campaign = session.api.post(CAMPAIGNS_PATH, content=content, content_type="application/yaml", name=arguments.name, start=True if arguments.start else None, kind="campaign", origin="cli")
    session.say(campaign_summary(campaign))
    return 0


def list_campaigns(session: Session, arguments: Namespace) -> int:
    campaigns = session.api.get(CAMPAIGNS_PATH, state=arguments.state or None, kind=arguments.kind, limit=arguments.limit, offset=arguments.offset)
    if not campaigns:
        session.say("no campaigns")
        return 0
    session.say(table(["id", "name", "kind", "origin", "steps", "desired", "actual", "created"], [campaign_row(c) for c in campaigns]))
    return 0


def show(session: Session, arguments: Namespace) -> int:
    campaign = session.api.get(campaign_path(arguments.campaign))
    session.say(campaign_summary(campaign))
    session.say()
    session.say(coverage_table(campaign["fecs"]))
    return 0


def control(name: str) -> Callable[[Session, Namespace], int]:
    def run(session: Session, arguments: Namespace) -> int:
        campaign = session.api.post(campaign_path(arguments.campaign, f"/{name}"))
        session.say(f"campaign {campaign['campaign_id']}: desired {campaign['desired_state']}, actual {campaign['actual_state']}")
        return 0

    return run


def delete(session: Session, arguments: Namespace) -> int:
    session.api.delete(campaign_path(arguments.campaign))
    session.say(f"deleted campaign {arguments.campaign}")
    return 0


def outputs(session: Session, arguments: Namespace) -> int:
    found = session.api.get(campaign_path(arguments.campaign, "/outputs"), step=arguments.step, state=arguments.state, fec_id=arguments.fec_id, limit=arguments.limit, offset=arguments.offset)
    if not found:
        session.say(f"no {arguments.step} outputs")
        return 0
    session.say(table(OUTPUT_HEADERS, [output_row(o) for o in found]))
    return 0


def findings(session: Session, arguments: Namespace) -> int:
    session.say(findings_summary(session.api.get(campaign_path(arguments.campaign, "/findings"), step=arguments.step)))
    return 0


def cases(session: Session, arguments: Namespace) -> int:
    found = session.api.get(campaign_path(arguments.campaign, "/cases"), fec_id=arguments.fec_id, state=arguments.state, stage=arguments.stage, limit=arguments.limit, offset=arguments.offset)
    if not found:
        session.say("no cases")
        return 0
    session.say(table(["FEC", "index", "case", "stage", "state", "seed", "reason"], [[c["fec_id"], c["case_index"], c["case_id"], c["stage"], c["state"], c["seed"], c["reason"]] for c in found]))
    return 0


def verdicts(session: Session, arguments: Namespace) -> int:
    path = campaign_path(arguments.campaign, "/verdicts")
    filters = dict(fec_id=arguments.fec_id, state=arguments.state, run_index=arguments.run, sensitive=True if arguments.sensitive else None, sort=arguments.sort, order=arguments.order)
    if arguments.csv:
        size = session.api.download(path, Path(arguments.csv), format="csv", **filters)
        session.say(f"wrote {size} bytes to {arguments.csv}")
        return 0
    found = session.api.get(path, limit=arguments.limit, offset=arguments.offset, **filters)
    if not found:
        session.say("no monitor result summaries")
        return 0
    rows = [[v["fec_id"], v["case_id"], v["run_index"], v["state"], ";".join(v["failed_rules"]), v["first_failure_time_s"], v["sensitive"]] for v in found]
    session.say(table(["FEC", "case", "run", "state", "failed rules", "first failure s", "sensitive"], rows))
    return 0


def _print_events(session: Session, events: list) -> None:
    for event in events:
        where = f" {event['fec_id']}" if event["fec_id"] else ""
        detail = f" {event['detail']}" if event["detail"] else ""
        session.say(f"{event['event_id']:>6}  {event['at']}  {event['kind']}{where}{detail}")


def events(session: Session, arguments: Namespace) -> int:
    path = campaign_path(arguments.campaign, "/events")
    after = arguments.after
    newest = arguments.newest  # the first batch only: the following polls page forward from its last event
    while True:
        if newest is not None:
            batch = session.api.get(path, after=after, newest=newest)
            newest = None
        else:
            batch = session.api.get(path, after=after, limit=FOLLOW_PAGE if arguments.follow else arguments.limit)
        _print_events(session, batch)
        if batch:
            after = batch[-1]["event_id"]
        if not arguments.follow:
            return 0
        if len(batch) == FOLLOW_PAGE:
            continue
        # Read the state after the events: a final campaign has no more to say once this batch came back empty
        if not batch and session.api.get(campaign_path(arguments.campaign))["actual_state"] in FINAL_STATES:
            return 0
        session.sleep(arguments.interval)


def artifact(session: Session, arguments: Namespace) -> int:
    target = Path(arguments.out)
    size = session.api.download(f"{ARTIFACTS_PATH}/{arguments.sha256}", target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != arguments.sha256:
        target.unlink(missing_ok=True)
        raise ApiError(None, [f"the downloaded bytes hash to {digest}, not {arguments.sha256}; the file was removed"])
    session.say(f"wrote {size} bytes to {arguments.out}")
    return 0
