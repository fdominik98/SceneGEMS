"""Stands in for the Refinery model generator in tests: `python stand_in_generator.py job -folder <folder>`.

It speaks the generator's job folder protocol (scenegems/README.md of the Refinery repository): it reads the
payload from <folder>/job.json, writes status lines and a log line to its standard output and leaves
<folder>/result.json. It rejects payload fields the generator does not know. What it does is chosen by the first
line of the problem:

    // stand-in: error     the problem does not parse: an error document, exit code 1
    // stand-in: crash     ends with exit code 3 and no result document
    // stand-in: garbage   a result document with neither a result nor an error
    // stand-in: hang      reports that it loads and then never ends
    anything else          max_models models (2 without a cap), each the generated model of this folder; the
                           result's message is the payload it was given, as JSON
"""

import json
import sys
import time
from pathlib import Path

STATUS_LINE_PREFIX = "scenegems-status "
FIELDS = {"problem", "max_models", "scopes", "scope_overrides", "random_seed", "timeout_s", "load_timeout_s", "state_coder_depth", "status_interval_s", "include_sources"}
MODEL = (Path(__file__).parent / "generated_model.problem").read_text(encoding="utf-8")


def status(message, progress, **fields):
    print(STATUS_LINE_PREFIX + json.dumps({"message": message, "progress": progress, **fields}), flush=True)


def leave(folder: Path, document: dict) -> None:
    (folder / "result.json").write_text(json.dumps(document), encoding="utf-8")


def main(arguments) -> int:
    if arguments[:2] != ["job", "-folder"] or len(arguments) != 3:
        print(f"usage: job -folder <folder>, got {arguments}", file=sys.stderr)
        return 2
    folder = Path(arguments[2])
    payload = json.loads((folder / "job.json").read_text(encoding="utf-8"))["job"]["payload"]
    behavior = payload["problem"].splitlines()[0].removeprefix("// stand-in:").strip() if payload["problem"].startswith("// stand-in:") else ""
    print("Loading the problem", flush=True)  # a log line: not a status
    unknown = sorted(set(payload) - FIELDS)
    if unknown:
        leave(folder, {"error": f"Unknown payload fields: {', '.join(unknown)}", "retryable": False})
        return 1
    status("loading the problem", None, phase="loading")
    if behavior == "hang":
        time.sleep(600)
    if behavior == "crash":
        return 3
    if behavior == "error":
        leave(folder, {"error": "the problem has errors: line 1: no such class Missing", "retryable": False})
        return 1
    if behavior == "garbage":
        leave(folder, {"neither": "a result nor an error"})
        return 0
    count = payload.get("max_models") or 2
    status(f"generating models: 1 of {count} found", 1 / count, phase="generating", models_found=1)
    result = {
        "stop_reason": "cap_reached" if payload.get("max_models") else "exhausted",
        "complete": not payload.get("max_models"),
        "models_found": count,
        "max_models": payload.get("max_models"),
        "random_seed": payload["random_seed"],
        "elapsed_s": 0.25,
        "message": json.dumps(payload, sort_keys=True),
        "models": [{"index": index, "file": f"models/model_{index:05d}.problem", "source": MODEL} for index in range(count)],
    }
    leave(folder, {"result": result})
    status(f"finished: {count} models", 1.0, phase="finished", models_found=count)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
