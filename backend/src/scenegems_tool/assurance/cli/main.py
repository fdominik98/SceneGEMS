"""The campaign command line: argument parsing, the API connection and the exit codes.

Exit codes: 0 success, 1 the API refused the request or could not be reached (the server's
reasons are printed to stderr), 2 a usage error, 130 interrupted while following events.
"""

import argparse
import os
import re
import sys
from typing import Callable, Dict, Optional, Sequence, TextIO

import httpx

from scenegems_tool.assurance.cli import commands
from scenegems_tool.assurance.cli.api_client import ApiError, OperatorApi

OPERATOR_URL_VARIABLE = "SCENEGEMS_OPERATOR_URL"
DEFAULT_OPERATOR_URL = "http://127.0.0.1:5174"
SHA256_PATTERN = "[0-9a-f]{64}"
CAMPAIGN_STATES = ("created", "running", "paused", "draining", "stalled", "stopped", "completed")
CAMPAIGN_KINDS = ("campaign", "workbench")
CAMPAIGN_STEPS = ("scene_generation", "trajectory_generation", "simulation")
CASE_STATES = ("active", "complete", "dropped", "failed", "cancelled")
CASE_STAGES = ("generate_scene", "generate_trajectories", "simulate", "monitor", "calibrate", "verdict")
VERDICT_STATES = ("passed", "failed", "unmonitored")

DESCRIPTION = """Create and watch assurance campaigns on a SceneGEMS master through its operator API.

The operator API has no authentication yet, so a master serves it on its loopback address
only (127.0.0.1:5174). From another machine reach it over SSH, for example
`ssh -L 5174:127.0.0.1:5174 <master>`, and keep the default --api.
"""

CONTROL_HELP = {
    "start": "set the desired state to running (the engine starts the campaign)",
    "pause": "hold queued jobs and start no new cases",
    "drain": "finish the started cases and start no new ones",
    "resume": "end a pause or a drain: the desired state is running again",
    "stop": "cancel queued and leased jobs; final",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scenegems_tool.assurance", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=os.environ.get(OPERATOR_URL_VARIABLE, DEFAULT_OPERATOR_URL), help=f"operator API base URL (default: ${OPERATOR_URL_VARIABLE}, else {DEFAULT_OPERATOR_URL})")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    create = sub.add_parser("create", help="create a campaign from a YAML config")
    create.add_argument("config", help="the campaign config file (YAML or JSON)")
    create.add_argument("--name", help="campaign name (default: the config's name)")
    create.add_argument("--start", action="store_true", help="set the desired state to running at once (default: the campaign waits paused)")

    listing = sub.add_parser("list", help="list campaigns, newest first")
    listing.add_argument("--state", action="append", choices=CAMPAIGN_STATES, help="only campaigns in this actual state (repeatable)")
    listing.add_argument("--kind", choices=CAMPAIGN_KINDS, help="only campaigns or only workbench entries")
    _paging(listing)

    show = sub.add_parser("show", help="a campaign with its coverage per FEC")
    show.add_argument("campaign")

    for name, help_text in CONTROL_HELP.items():
        control = sub.add_parser(name, help=help_text, description=help_text)
        control.add_argument("campaign")

    delete = sub.add_parser("delete", help="delete a stopped or completed campaign with its rows and references")
    delete.add_argument("campaign")

    outputs = sub.add_parser("outputs", help="the outputs of one step of a campaign")
    outputs.add_argument("campaign")
    outputs.add_argument("--step", required=True, choices=CAMPAIGN_STEPS)
    outputs.add_argument("--fec", dest="fec_id", help="only this FEC id")
    outputs.add_argument("--state", choices=CASE_STATES)
    _paging(outputs)

    findings = sub.add_parser("findings", help="the monitor findings (or statistics) of one step of a campaign")
    findings.add_argument("campaign")
    findings.add_argument("--step", required=True, choices=CAMPAIGN_STEPS)

    cases = sub.add_parser("cases", help="the cases of a campaign")
    cases.add_argument("campaign")
    cases.add_argument("--fec", dest="fec_id", help="only this FEC id")
    cases.add_argument("--state", choices=CASE_STATES)
    cases.add_argument("--stage", choices=CASE_STAGES)
    _paging(cases)

    verdicts = sub.add_parser("verdicts", help="the verdicts of a campaign")
    verdicts.add_argument("campaign")
    verdicts.add_argument("--fec", dest="fec_id", help="only this FEC id")
    verdicts.add_argument("--state", choices=VERDICT_STATES)
    verdicts.add_argument("--run", type=int, help="only this run index")
    verdicts.add_argument("--sensitive", action="store_true", help="only sensitive verdicts")
    verdicts.add_argument("--csv", metavar="FILE", help="write every matching verdict to this CSV file instead of printing a page")
    _paging(verdicts)

    events = sub.add_parser("events", help="the audit trail of a campaign")
    events.add_argument("campaign")
    events.add_argument("--after", type=int, default=0, help="only events after this event id")
    events.add_argument("--limit", type=int, default=100)
    events.add_argument("--follow", action="store_true", help="keep polling until interrupted or the campaign is stopped or completed")
    events.add_argument("--interval", type=float, default=2.0, help="seconds between polls with --follow")

    artifact = sub.add_parser("artifact", help="download a stored artifact by its sha256")
    artifact.add_argument("sha256", help="the artifact hash (64 lowercase hex digits)")
    artifact.add_argument("--out", required=True, metavar="FILE")
    return parser


def _paging(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=100, help="entries per page (the server allows 1000)")
    parser.add_argument("--offset", type=int, default=0)


def _handlers() -> Dict[str, Callable]:
    handlers: Dict[str, Callable] = {
        "create": commands.create,
        "list": commands.list_campaigns,
        "show": commands.show,
        "delete": commands.delete,
        "outputs": commands.outputs,
        "findings": commands.findings,
        "cases": commands.cases,
        "verdicts": commands.verdicts,
        "events": commands.events,
        "artifact": commands.artifact,
    }
    handlers.update({name: commands.control(name) for name in CONTROL_HELP})
    return handlers


def main(argv: Optional[Sequence[str]] = None, transport: Optional[httpx.BaseTransport] = None, out: Optional[TextIO] = None, err: Optional[TextIO] = None, sleep: Optional[Callable] = None) -> int:
    """Runs one command. transport, out, err and sleep are for tests."""
    out, err = out or sys.stdout, err or sys.stderr
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "artifact":
        if not re.fullmatch(SHA256_PATTERN, arguments.sha256):
            parser.error("the artifact hash is 64 lowercase hex digits")
    api = OperatorApi(arguments.api, transport=transport)
    session = commands.Session(api, out, err, **({"sleep": sleep} if sleep else {}))
    try:
        return _handlers()[arguments.command](session, arguments)
    except ApiError as error:
        prefix = f"error: HTTP {error.status}: " if error.status else "error: "
        print(prefix + error.reasons[0], file=err)
        for reason in error.reasons[1:]:
            print(f"  {reason}", file=err)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        api.close()
