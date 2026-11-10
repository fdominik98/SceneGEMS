"""The architecture files: written at control node startup, read by the operator API.

backend/assets/architecture holds one YAML file per document and an index. They are generated from the specs in code,
so they are not tracked in git and nothing edits them by hand; measured values stay in their own files (the vessel stack's
registry file, subsystems/measured_capabilities.yaml) and are merged in when the files are written.

The writer runs in a background thread at startup and never stops the control node: a folder that cannot be written is logged and
the API builds the documents in memory instead.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from scenegems_tool.architecture.architecture_model import SCHEMA_VERSION, to_plain
from utils.file_system_utils import ASSET_FOLDER

logger = logging.getLogger(__name__)

ARCHITECTURE_FOLDER = f"{ASSET_FOLDER}/architecture"
INDEX_FILE = "index.yaml"

_HEADER = "# Generated at control node startup from the specs in code (scenegems_tool/architecture). Do not edit: the next start rewrites it.\n"
_FileStamp = Tuple[Tuple[str, int], ...]
_cache: Dict[str, Tuple[_FileStamp, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def document_file(document_id: str) -> str:
    return f"{document_id}.yaml"


def write_architecture_files(folder: Optional[str] = None) -> List[Path]:
    """Build the documents and write one YAML file each plus the index; returns the files in index order."""
    from scenegems_tool.architecture.architecture_catalog import build_architecture_documents  # the specs pull in the vessel stack and numpy, which the control node's startup avoids

    target = Path(folder or ARCHITECTURE_FOLDER)
    target.mkdir(parents=True, exist_ok=True)
    documents = build_architecture_documents()
    written = [_write_yaml(target / document_file(document.id), document.to_dict()) for document in documents.values()]
    index = {
        "schema_version": SCHEMA_VERSION,
        "documents": [{"id": document.id, "title": document.title, "summary": document.summary, "file": document_file(document.id)} for document in documents.values()],
    }
    written.append(_write_yaml(target / INDEX_FILE, index))
    return written


def read_architecture_files(folder: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The index and the documents as plain data, or None when a file is missing or from another schema version."""
    source = Path(folder or ARCHITECTURE_FOLDER)
    index_path = source / INDEX_FILE
    try:
        index = _load_yaml(index_path)
        if index.get("schema_version") != SCHEMA_VERSION:
            return None
        paths = [source / entry["file"] for entry in index["documents"]]
        stamp = tuple((str(path), path.stat().st_mtime_ns) for path in (index_path, *paths))
        with _cache_lock:
            cached = _cache.get(str(source))
            if cached is not None and cached[0] == stamp:
                return cached[1]
        view = {"schema_version": index["schema_version"], "documents": [_load_yaml(path) for path in paths]}
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        return None
    if any(document.get("schema_version") != SCHEMA_VERSION for document in view["documents"]):
        return None
    with _cache_lock:
        _cache[str(source)] = (stamp, view)
    return view


def architecture_view(folder: Optional[str] = None) -> Dict[str, Any]:
    """What the operator API serves: the files as written at startup, or the documents built now when the files are missing."""
    view = read_architecture_files(folder)
    if view is not None:
        return view
    from scenegems_tool.architecture.architecture_catalog import build_architecture_documents

    documents = build_architecture_documents()
    return {"schema_version": SCHEMA_VERSION, "documents": [document.to_dict() for document in documents.values()]}


def start_architecture_files_writer(folder: Optional[str] = None) -> threading.Thread:
    """Write the files in a daemon thread. A failure is logged, not raised."""

    def run() -> None:
        try:
            files = write_architecture_files(folder)
            logger.info("Architecture description written to %s (%d files)", Path(files[0]).parent, len(files))
        except Exception:
            logger.warning("Could not write the architecture description files; the operator API builds them on request", exc_info=True)

    thread = threading.Thread(target=run, name="architecture-files", daemon=True)
    thread.start()
    return thread


def _write_yaml(path: Path, data: Dict[str, Any]) -> Path:
    text = _HEADER + yaml.safe_dump(to_plain(data), sort_keys=False, allow_unicode=True, width=160)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return path


def _load_yaml(path: Path) -> Dict[str, Any]:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as file:
        return yaml.load(file, Loader=loader) or {}
