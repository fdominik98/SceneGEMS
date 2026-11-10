"""The artifact routes: worker nodes download job inputs and upload job results; the operator reads artifacts.

Worker node API (plain HTTP on the VPN; the worker node names itself in the X-Worker-Node-Id header, nothing is authenticated):

    GET <ARTIFACTS_PATH>/<sha256>   the content; with `Accept-Encoding: gzip` the stored gzip bytes
                                    as `Content-Encoding: gzip` (the worker node client asks for it), otherwise
                                    the uncompressed bytes. 404 when the store does not hold it.
    PUT <ARTIFACTS_PATH>/<sha256>?kind=<ArtifactKind>[&job_id=<id>&field=<result field>]
                                    the content as the body, `Content-Encoding: identity` or `gzip`
                                    (the worker node client compresses), `Content-Type` its media type.
                                    The body is streamed into the store and its uncompressed bytes
                                    must hash to <sha256> (422 otherwise) and stay within the size
                                    limit (413). With job_id the job must be leased to this worker node
                                    (409 otherwise), and the job references the artifact in the role
                                    `result:<field>`. 201 when the artifact is new, 200 when it was
                                    stored already; the body is the reference with its stored size.

Operator API (the operator listener, no authentication yet, as the other operator routes):

    GET and HEAD <ARTIFACTS_PATH>/<sha256>   as the worker node's GET
    POST <ARTIFACTS_PATH>?kind=<functional_scenario|scene|trajectories>
                                    stores the body as an artifact of the operator's file: `Content-Type` is
                                    its media type (JSON by default), the body is not compressed (Content-Encoding
                                    identity) and stays within the size limit of worker node uploads (413). The artifact
                                    is held by an `upload` reference that expires after UPLOAD_HOLD (24 hours); a
                                    campaign created with it takes over (the pipeline's `campaign` reference), and the
                                    sweep frees it once the hold expired and nothing else references it. The body is
                                    spooled while it is hashed, since the operator does not know its hash. 201 when the
                                    artifact is new, 200 when it was stored already; the body is its reference
                                    (sha256, size_bytes, kind, media_type, pointer null). An artifact stored
                                    before under another kind keeps that kind.

Bodies are never held in memory whole: uploads go through the store's writer in chunks,
downloads stream from the file. Compression and hashing run in worker threads, so a large
upload does not stall the control sockets on the same event loop.
"""

import hashlib
import logging
import re
import tempfile
import zlib
from datetime import timedelta
from typing import BinaryIO, Callable, Iterator, Optional

import anyio
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from scenegems_tool.cluster.protocol.artifacts import JSON_MEDIA_TYPE, SHA256_PATTERN, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.cluster.protocol.routes import ARTIFACTS_PATH, WORKER_NODE_ID_HEADER
from scenegems_tool.cluster.scope_names import is_scope_name
from scenegems_tool.persistence.artifacts.artifact_store import COMPRESSED_ENCODING, ArtifactHashMismatch, ArtifactNotFound, ArtifactTooLarge, ArtifactWriter
from scenegems_tool.persistence.artifacts.recorded_artifacts import ArtifactHolder, RecordedArtifacts, result_role
from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import ArtifactHolderKind
from scenegems_tool.persistence.stores.artifact_records import ArtifactMismatch, UnknownArtifact

logger = logging.getLogger(__name__)

ARTIFACT_PATH = ARTIFACTS_PATH + "/{sha256}"
DEFAULT_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
STREAM_CHUNK_BYTES = 1024 * 1024  # the unit of reading, decompressing and writing
OCTET_STREAM = "application/octet-stream"
UPLOAD_KINDS = ("functional_scenario", "scene", "trajectories")  # what the operator may upload; the kinds are strings in the records
UPLOAD_HOLD = timedelta(hours=24)  # how long an upload without a campaign is kept
SPOOL_MEMORY_BYTES = 8 * 1024 * 1024  # an upload up to this size is spooled in memory, a larger one on disk
_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_MEDIA_TYPE = re.compile(r"^[\x21-\x7e][\x20-\x7e]{0,127}$")

JobHolder = Callable[[str], Optional[str]]  # job id to the worker node holding its active lease; called in a worker thread
Sha256 = Path(pattern=SHA256_PATTERN, description="sha256 of the uncompressed content")


def lease_holder_of(job_store) -> JobHolder:
    """The worker node that holds the job's lease (offered or running), from a job store."""

    def holder(job_id: str) -> Optional[str]:
        job = job_store.get(job_id)
        return job.lease_owner if job is not None and job.state in (JobState.LEASED, JobState.RUNNING) else None

    return holder


def worker_node_artifact_router(artifacts: RecordedArtifacts, job_holder: JobHolder, max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES) -> APIRouter:
    router = APIRouter()

    async def worker_node_of(request: Request) -> str:
        worker_node_id = request.headers.get(WORKER_NODE_ID_HEADER, "")
        if not is_scope_name(worker_node_id):
            raise HTTPException(status_code=400, detail=f"send the worker node's id in the {WORKER_NODE_ID_HEADER} header (1 to 63 lowercase letters, digits and hyphens)")
        return worker_node_id

    @router.get(ARTIFACT_PATH)
    async def download(request: Request, sha256: str = Sha256) -> Response:
        await worker_node_of(request)
        return await artifact_response(artifacts, sha256, request)

    @router.put(ARTIFACT_PATH)
    async def upload(
        request: Request,
        sha256: str = Sha256,
        kind: ArtifactKind = Query(...),
        job_id: Optional[str] = Query(None, max_length=128),
        field: Optional[str] = Query(None, max_length=48),
    ) -> Response:
        worker_node_id = await worker_node_of(request)
        encoding = _upload_encoding(request, max_bytes)
        media_type = _media_type(request)
        holder = await _job_holder(job_holder, worker_node_id, job_id, field) if job_id is not None else None
        recorded = await receive(artifacts, sha256, request, encoding, max_bytes, kind.value, media_type, holder)
        body = {
            "sha256": sha256,
            "size_bytes": recorded.stored.size_bytes,
            "kind": recorded.record.kind,
            "media_type": recorded.record.media_type,
            "stored_size_bytes": recorded.stored.stored_size_bytes,
            "created": recorded.recorded,
        }
        if recorded.recorded:
            logger.info("Worker node %s stored artifact %s (%s, %d bytes)", worker_node_id, sha256, kind.value, recorded.stored.size_bytes)
        return JSONResponse(body, status_code=201 if recorded.recorded else 200)

    return router


def operator_artifact_router(artifacts: RecordedArtifacts, max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES, clock: Clock = utc_now) -> APIRouter:
    router = APIRouter()

    @router.post(ARTIFACTS_PATH)
    async def upload(request: Request, kind: str = Query(...)) -> Response:
        if kind not in UPLOAD_KINDS:
            raise HTTPException(status_code=422, detail=f"kind is one of {', '.join(UPLOAD_KINDS)}, not {kind!r}")
        if _upload_encoding(request, max_bytes) != "identity":
            raise HTTPException(status_code=415, detail="the operator's upload is not compressed; send Content-Encoding identity")
        media_type = _media_type(request)
        with tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES) as spool:
            sha256, size = await _spool(request, spool, max_bytes)
            if size == 0:
                raise HTTPException(status_code=422, detail="the body is empty")
            recorded = await _store_spooled(artifacts, spool, sha256, max_bytes, kind, media_type)
        try:
            await anyio.to_thread.run_sync(artifacts.records.add_upload_reference, sha256, clock() + UPLOAD_HOLD)
        except UnknownArtifact:
            raise HTTPException(status_code=409, detail=f"artifact {sha256} was swept while it was uploaded; upload it again") from None
        if recorded.recorded:
            logger.info("The operator uploaded artifact %s (%s, %d bytes)", sha256, kind, size)
        reference = {"sha256": sha256, "size_bytes": recorded.stored.size_bytes, "kind": recorded.record.kind, "media_type": recorded.record.media_type, "pointer": None}
        return JSONResponse(reference, status_code=201 if recorded.recorded else 200)

    @router.get(ARTIFACT_PATH)
    async def download(request: Request, sha256: str = Sha256) -> Response:
        return await artifact_response(artifacts, sha256, request)

    @router.head(ARTIFACT_PATH)
    async def head(request: Request, sha256: str = Sha256) -> Response:
        return await artifact_response(artifacts, sha256, request, body=False)

    return router


# Downloads


def accepts_gzip(request: Request) -> bool:
    for item in request.headers.get("accept-encoding", "").split(","):
        coding, _, parameters = item.strip().partition(";")
        if coding.strip().lower() == COMPRESSED_ENCODING:
            quality = parameters.strip().lower()
            return not (quality.startswith("q=") and _quality(quality[2:]) == 0.0)
    return False


def _quality(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 1.0


async def artifact_response(artifacts: RecordedArtifacts, sha256: str, request: Request, body: bool = True) -> Response:
    compressed = accepts_gzip(request)
    try:
        stream = await anyio.to_thread.run_sync(artifacts.open, sha256, compressed)
    except ArtifactNotFound:
        raise HTTPException(status_code=404, detail=f"no artifact {sha256}") from None
    try:
        record = await anyio.to_thread.run_sync(artifacts.record, sha256)
        if compressed:
            length = await anyio.to_thread.run_sync(artifacts.store.stored_size, sha256)
        else:
            length = record.size_bytes if record is not None else await anyio.to_thread.run_sync(artifacts.store.size, sha256)
    except BaseException:
        stream.close()
        raise
    headers = {"Content-Length": str(length), "ETag": f'"{sha256}"', "Cache-Control": "private, max-age=31536000, immutable", "Vary": "Accept-Encoding"}
    if compressed:
        headers["Content-Encoding"] = COMPRESSED_ENCODING
    media_type = record.media_type if record is not None else OCTET_STREAM
    if not body:
        stream.close()
        return Response(status_code=200, headers=headers, media_type=media_type)
    return StreamingResponse(_chunks(stream), headers=headers, media_type=media_type)


def _chunks(stream) -> Iterator[bytes]:
    """A synchronous iterator, which Starlette runs in its thread pool."""
    try:
        while True:
            chunk = stream.read(STREAM_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk
    finally:
        stream.close()


# Uploads


def _upload_encoding(request: Request, max_bytes: int) -> str:
    """The body's content coding; a body that declares a length over the limit is refused before it is read."""
    encoding = request.headers.get("content-encoding", "identity").strip().lower() or "identity"
    if encoding not in ("identity", COMPRESSED_ENCODING):
        raise HTTPException(status_code=415, detail=f"unsupported Content-Encoding {encoding!r}; send identity or gzip")
    declared = request.headers.get("content-length", "")
    if encoding == "identity" and declared.isdigit() and int(declared) > max_bytes:
        raise HTTPException(status_code=413, detail=f"the artifact exceeds the limit of {max_bytes} bytes")
    return encoding


async def _job_holder(job_holder: JobHolder, worker_node_id: str, job_id: str, field: Optional[str]) -> ArtifactHolder:
    """The job's reference to its uploaded result field; the job must be leased to the uploading worker node."""
    if field is None or not _FIELD_NAME.match(field):
        raise HTTPException(status_code=422, detail="an upload for a job names its result field (lowercase letters, digits and '_')")
    if await anyio.to_thread.run_sync(job_holder, job_id) != worker_node_id:
        raise HTTPException(status_code=409, detail=f"job {job_id} is not leased to this worker node")
    return ArtifactHolder(ArtifactHolderKind.JOB, job_id, result_role(field))


def _media_type(request: Request) -> str:
    media_type = request.headers.get("content-type", "").strip() or JSON_MEDIA_TYPE
    if not _MEDIA_TYPE.match(media_type):
        raise HTTPException(status_code=422, detail="invalid Content-Type")
    return media_type


async def _spool(request: Request, spool: BinaryIO, max_bytes: int) -> tuple:
    """Copies the request body into the spool while hashing it; returns its sha256 and size. 413 beyond max_bytes."""
    digest = hashlib.sha256()
    size = 0

    def feed(data: bytes) -> None:
        nonlocal size
        size += len(data)
        if size > max_bytes:
            raise ArtifactTooLarge(max_bytes)
        digest.update(data)
        spool.write(data)

    try:
        pending = bytearray()
        async for chunk in request.stream():
            pending += chunk
            if len(pending) >= STREAM_CHUNK_BYTES:
                await anyio.to_thread.run_sync(feed, bytes(pending))
                pending.clear()
        if pending:
            await anyio.to_thread.run_sync(feed, bytes(pending))
    except ArtifactTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from None
    return digest.hexdigest(), size


async def _store_spooled(artifacts: RecordedArtifacts, spool: BinaryIO, sha256: str, max_bytes: int, kind: str, media_type: str):
    """Writes the spooled body into the store under its hash and records it."""

    def store():
        spool.seek(0)
        with artifacts.writer(sha256, max_bytes) as writer:
            while True:
                chunk = spool.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                writer.write(chunk)
            return artifacts.commit(writer, kind, media_type, None)

    try:
        return await anyio.to_thread.run_sync(store)
    except ArtifactTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from None
    except ArtifactMismatch as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


class _Inflater:
    """Decompresses gzip members in bounded pieces, so a small body cannot expand into memory at once."""

    def __init__(self, writer: ArtifactWriter):
        self._writer = writer
        self._decompressor = zlib.decompressobj(wbits=31)

    def feed(self, data: bytes) -> None:
        while True:
            if self._decompressor.eof:
                data = self._decompressor.unused_data + data
                if not data:
                    return
                self._decompressor = zlib.decompressobj(wbits=31)  # concatenated members form one gzip stream
            output = self._decompressor.decompress(data, STREAM_CHUNK_BYTES)
            self._writer.write(output)
            data = self._decompressor.unconsumed_tail
            if data or (self._decompressor.eof and self._decompressor.unused_data):
                continue
            if len(output) < STREAM_CHUNK_BYTES or self._decompressor.eof:
                return  # all input used and nothing pending; a full piece may leave output behind, so go again

    def finish(self) -> None:
        if not self._decompressor.eof:
            raise zlib.error("the gzip body ends early")


async def receive(artifacts: RecordedArtifacts, sha256: str, request: Request, encoding: str, max_bytes: int, kind: str, media_type: str, holder: Optional[ArtifactHolder]):
    writer = await anyio.to_thread.run_sync(artifacts.writer, sha256, max_bytes)
    sink = _Inflater(writer) if encoding == COMPRESSED_ENCODING else None
    write = sink.feed if sink is not None else writer.write
    try:
        pending = bytearray()
        async for chunk in request.stream():
            pending += chunk
            if len(pending) >= STREAM_CHUNK_BYTES:
                await anyio.to_thread.run_sync(write, bytes(pending))
                pending.clear()
        if pending:
            await anyio.to_thread.run_sync(write, bytes(pending))
        if sink is not None:
            await anyio.to_thread.run_sync(sink.finish)
        return await anyio.to_thread.run_sync(artifacts.commit, writer, kind, media_type, holder)
    except ArtifactTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from None
    except ArtifactHashMismatch as error:
        raise HTTPException(status_code=422, detail=f"hash mismatch: {error}") from None
    except zlib.error as error:
        raise HTTPException(status_code=400, detail=f"invalid gzip body: {error}") from None
    except ArtifactMismatch as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    finally:
        await anyio.to_thread.run_sync(writer.abort)
