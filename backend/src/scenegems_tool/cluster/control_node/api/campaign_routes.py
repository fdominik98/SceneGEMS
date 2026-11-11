"""The operator's campaign routes: create, read and control campaigns (Phase 4).

Like the job and worker node routes (operator_routes.py) they have no authentication yet and are
served on the operator listener only. They are a thin layer on the AssuranceStores; the
pipeline engine in the control node (P4.4) converges a campaign onto the desired state these
routes set. Without Postgres stores the control node mounts unavailable_router instead.

    POST CAMPAIGNS_PATH/validate           the same body as create, nothing is created: 200 with {"valid": true, "name", "config_hash",
                                           "fecs" (fec_id, content hash, counts, quota, failure budget: null when it is unlimited), "cases_planned" (the quotas' sum),
                                           "runs" (index, name, repeatability tier, warnings)}, or the 422 create answers
    POST CAMPAIGNS_PATH?name=&start=&kind=&origin=       create from a config; 201 with the campaign. The body is the config as
                                           YAML text (Content-Type application/yaml, text/yaml or application/x-yaml;
                                           JSON is YAML too) or a JSON object {"config": {...}, "name": "...",
                                           "start": false, "kind": "campaign", "origin": "wizard"} (application/json).
                                           The campaign waits paused unless start is true. kind is campaign (the
                                           default) or workbench, origin says who made it (wizard and cli for a campaign,
                                           scene_generation, trajectory_generation, simulation and live_session for a
                                           workbench entry; it implies the kind when that is left out); both travel
                                           beside the config, not in it, so they do not change its hash. The artifacts
                                           the config's input names are checked against the control node's artifact store. The
                                           pipeline engine is woken, so the campaign does not wait for the next tick.
                                           COLREGS constants, vessel types and obstacle types the config leaves out come
                                           from the cluster's domain configuration (preset_routes.py), so the stored config
                                           and its hash hold the contents the campaign runs with
                                           422 with {"message", "reasons"} for a config that does not load or that the
                                           catalog, the artifact store or the vessel stack resolver refuses
    GET  CAMPAIGNS_PATH?state=&kind=&origin=&q=&limit=&offset=      campaigns, newest first; state, kind and origin are repeatable,
                                           q is a case-insensitive part of the name. A row adds steps, input (first_step, item_count),
                                           made_from (campaign ids of its items) and totals (cases by state, verdicts by step and state)
    DELETE <id>                            deletes a final campaign with its rows and references: 204, 404, or 409 until it is
                                           stopped or completed
    GET  <id>                              the campaign with its FECs (fecs: counts, state, verdicts per run and state) and totals
                                           (fecs, fecs_open, ...); a FEC's failure_budget and failure_budget_left are null when its
                                           failure budget is unlimited
    GET  <id>/fecs                         the FECs alone
    GET  <id>/cases?fec_id=&state=&stage=&limit=&offset=      cases by FEC and index
    GET  <id>/cases/<case id>              the case with its jobs, run records and verdicts. A case names its input_artifact (the
                                           functional scenario or item it started from, null for a catalog FEC) and input_source
    GET  <id>/outputs?step=&state=&fec_id=&limit=&offset=      the outputs of a step (scene_generation, trajectory_generation or
                                           simulation) by FEC and case: the artifact, whether it is valid and complete, the step's verdict
                                           and where the input came from; a row per run for the simulation. 422 for a step the campaign does not run.
                                           step=design_space_exploration lists the FECs the exploration found, in the same row shape: a row per
                                           explored FEC (fec_id explored/<index>, case_index the index, case_id the exploration case) with its
                                           functional scenario as the artifact and its vessel_count and obstacle_count; empty until the
                                           exploration has finished; state and fec_id do not narrow it
    GET  <id>/findings?step=               (422 for design_space_exploration, which no monitor judges)
                                           the summary of a step for Results: cases by state, outputs, verdicts, failed rules, encounter_types (vessel
                                           pairs by the first encounter type of each), FECs (fecs), durations; statistics only for a step the config
                                           does not monitor
    GET  <id>/verdicts?fec_id=&state=&run_index=&sensitive=&step=&sort=&order=&limit=&offset=&format=       verdicts, by default by FEC, case, step and run;
                                           step is scene, trajectories or simulation; sort is fec_id (that default order), state,
                                           first_failure_time_s, step, run_index, case_index or created_at, order asc (default) or desc;
                                           nulls come last in both directions and the verdict id breaks ties, so offset paging is stable.
                                           A verdict carries encounters (per relation as in rule_outcomes, the situation types by first
                                           appearance; null for older verdicts). format=csv answers every matching verdict as a CSV stream
                                           (limit, offset, sort and order still apply when given; encounters is a JSON cell)
    GET  <id>/run-records?fec_id=&run_index=&limit=&offset=      rows carry source (job or live_session); trajectory_generator is null for a live session
    GET  <id>/events?after=&limit=&newest=         the audit trail after an event id, oldest first; newest=N (1 to 1000) answers the N newest events
                                           after that id instead (limit does not apply), still oldest first
    GET  <id>/config                       the current config and every config version
    POST <id>/start | resume               desired state running
    POST <id>/pause                        desired state paused: queued jobs held, no new cases
    POST <id>/drain                        desired state draining: started cases finish, no new ones
    POST <id>/stop                         desired state stopped; final. 409 for any change of a stopped or finished campaign

The lists (campaigns, cases, outputs, verdicts, run records, events) answer the number of entries that match their filters without the
page in the X-Total-Count header. Verdicts and run records carry the case's index in its FEC (case_index) and the FEC as fec_id.

Control routes answer 200 with the campaign. The actual state follows when the engine has converged.

The campaigns topic of the live channel hears of every create, control and delete through the app state (campaigns_topic,
set by create_operator_app), the artifact store the input is checked against comes from there too (artifact_store).
"""

import csv
import inspect
import io
import json
from functools import partial
from typing import Any, Callable, Dict, Iterator, List, Literal, NamedTuple, Optional

import anyio
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from scenegems_tool.cluster.control_node.api.campaign_views import (
    DEFAULT_STEP_NAMES,
    EXPLORATION_STEP_NAME,
    STEP_NAMES,
    VERDICT_COLUMNS,
    campaign_detail_view,
    campaign_row_view,
    campaign_view,
    case_job_view,
    case_view,
    classes_view,
    config_monitored,
    config_version_view,
    event_view,
    findings_view,
    output_view,
    run_record_view,
    source_campaigns,
    validated_campaign_view,
    verdict_row,
    verdict_view,
)
from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.protocol.routes import CAMPAIGNS_PATH
from scenegems_tool.persistence.schema import (
    CampaignActualState,
    CampaignDesiredState,
    CampaignKind,
    CampaignOrigin,
    CaseState,
    PipelineStage,
    StepKind,
    VerdictState,
)
from scenegems_tool.persistence.stores import AssuranceStores, CampaignRecord, CampaignStateConflict, UnknownCampaign
from scenegems_tool.persistence.stores.result_store import VerdictSort

MAX_LISTED = 1000
NEWEST_EVENTS_MAX = 1000
TOTAL_COUNT_HEADER = "X-Total-Count"
CSV_PAGE = 1000
YAML_TYPES = ("application/yaml", "text/yaml", "application/x-yaml", "text/x-yaml")
CONTROLS = {
    "start": CampaignDesiredState.RUNNING,
    "resume": CampaignDesiredState.RUNNING,
    "pause": CampaignDesiredState.PAUSED,
    "drain": CampaignDesiredState.DRAINING,
    "stop": CampaignDesiredState.STOPPED,
}


def unavailable_router() -> APIRouter:
    """The campaign routes of a control node without Postgres stores: every one answers 503."""
    router = APIRouter()

    @router.api_route(CAMPAIGNS_PATH, methods=["GET", "POST", "DELETE"])
    @router.api_route(CAMPAIGNS_PATH + "/{rest:path}", methods=["GET", "POST", "DELETE"])
    async def unavailable(rest: str = "") -> None:
        raise HTTPException(status_code=503, detail="this control node runs without the campaign stores")

    return router


def _page(limit: int) -> int:
    return max(1, min(limit, MAX_LISTED))


async def _run(function: Callable[..., Any], *arguments: Any, **keywords: Any) -> Any:
    return await anyio.to_thread.run_sync(partial(function, *arguments, **keywords))


def _with_total(response: Response, total: int) -> None:
    response.headers[TOTAL_COUNT_HEADER] = str(total)


def _config_problem(reasons: List[str]) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": "the campaign config is not valid", "reasons": list(reasons)})


class CreateRequest(NamedTuple):
    text: str  # the config as YAML or JSON text
    name: Optional[str]
    start: bool
    kind: CampaignKind
    origin: Optional[CampaignOrigin]


def _choice(enum: Any, value: Any, label: str) -> Any:
    """The enum member a request names, or a 422 listing the members."""
    try:
        return enum(value)
    except ValueError:
        raise _config_problem([f'"{label}" is one of {", ".join(member.value for member in enum)}, not {value!r}'])


def _kind_and_origin(kind: Any, origin: Any) -> tuple:
    """The kind and origin of a create request. An origin alone implies its kind; the two must agree."""
    chosen_origin = None if origin is None else _choice(CampaignOrigin, origin, "origin")
    chosen_kind = chosen_origin.kind if kind is None and chosen_origin is not None else _choice(CampaignKind, CampaignKind.CAMPAIGN.value if kind is None else kind, "kind")
    if chosen_origin is not None and chosen_origin.kind != chosen_kind:
        raise _config_problem([f'origin "{chosen_origin.value}" belongs to kind "{chosen_origin.kind.value}", not "{chosen_kind.value}"'])
    return chosen_kind, chosen_origin


def _json_body(text: str, name: Optional[str], start: Optional[bool], kind: Optional[str], origin: Optional[str]) -> CreateRequest:
    """The create request of a JSON body: {"config": object or YAML text, "name", "start", "kind", "origin"}; the query's values win."""
    try:
        document = json.loads(text)
    except ValueError as error:
        raise _config_problem([f"not valid JSON: {error}"])
    if not isinstance(document, dict) or "config" not in document:
        raise _config_problem(['the body is an object with the config under "config", and optionally "name", "start", "kind" and "origin"'])
    unknown = sorted(set(document) - {"config", "name", "start", "kind", "origin"})
    if unknown:
        raise _config_problem([f"unknown fields in the body: {unknown}"])
    config = json.dumps(document["config"]) if isinstance(document["config"], dict) else document["config"]
    if not isinstance(config, str):
        raise _config_problem(['"config" is a config object or YAML text'])
    chosen_name = name if name is not None else document.get("name")
    if chosen_name is not None and (not isinstance(chosen_name, str) or not chosen_name.strip()):
        raise _config_problem(['"name" is a non-empty string'])
    chosen_start = start if start is not None else document.get("start", False)
    if not isinstance(chosen_start, bool):
        raise _config_problem(['"start" is true or false'])
    chosen_kind, chosen_origin = _kind_and_origin(kind if kind is not None else document.get("kind"), origin if origin is not None else document.get("origin"))
    return CreateRequest(config, chosen_name, chosen_start, chosen_kind, chosen_origin)


async def _request_config(request: Request, name: Optional[str], start: Optional[bool], kind: Optional[str] = None, origin: Optional[str] = None) -> CreateRequest:
    """The create request, from either body form."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    try:
        text = (await request.body()).decode("utf-8")
    except UnicodeDecodeError:
        raise _config_problem(["the body is not UTF-8 text"])
    if content_type in YAML_TYPES:
        return CreateRequest(text, name, bool(start), *_kind_and_origin(kind, origin))
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail=f"send the config as application/yaml or application/json, not {content_type or 'no content type'}")
    return _json_body(text, name, start, kind, origin)


def _validated_config(text: str, artifacts: Any = None, stores: Optional[AssuranceStores] = None, attended: bool = False) -> Any:
    """The config text checked against the catalog, the resolver and, for the artifacts its input names, the control node's artifact store
    (a RecordedArtifacts, None without one); a ValidatedCampaign, or 422 with every reason when it does not pass. Domain contents the
    config leaves out come from the cluster's domain configuration in stores, or the default presets while none is saved."""
    # Imported here: the config model pulls in numpy and the job type modules, which the control node keeps out of its startup
    from scenegems_tool.assurance.campaign import CampaignConfigError, parse_campaign_config, validate_campaign_config

    callables: Dict[str, Any] = {}
    if artifacts is not None:
        callables = {"artifact_exists": lambda sha256: artifacts.record(sha256) is not None, "read_artifact": artifacts.store.read}
    saved = stores.domain.current() if stores is not None else None
    try:
        # attended: a workbench entry, whose operator is there to start a run that waits for one
        return validate_campaign_config(parse_campaign_config(text, None if saved is None else saved.contents()), attended=attended, **callables)
    except CampaignConfigError as error:
        raise _config_problem(error.reasons)


def _step_kind(step: str) -> StepKind:
    """The verdict step of an API step name (scene_generation, trajectory_generation, simulation); the design space exploration has none."""
    if step == EXPLORATION_STEP_NAME:
        raise HTTPException(status_code=422, detail=f"{step} has no monitor result summaries; its outputs are the FECs it found")
    if step not in STEP_NAMES:
        raise HTTPException(status_code=422, detail=f"step is one of {', '.join(STEP_NAMES)}, not {step!r}")
    # Imported here with the config model (see _validated_config)
    from scenegems_tool.assurance.campaign.campaign_config import CampaignStep

    return CampaignStep(step).step_kind


def _artifact_store(request: Request) -> Any:
    return getattr(request.app.state, "artifact_store", None)


def _campaigns_topic(request: Request) -> Any:
    return getattr(request.app.state, "campaigns_topic", None)


def _announce(request: Request, campaign_id: str) -> None:
    """Tells the live channel's campaigns topic that a campaign was created or changed."""
    topic = _campaigns_topic(request)
    if topic is not None:
        topic.campaigns_changed({campaign_id})


async def _wake_pipeline(plane: ControlPlane) -> None:
    """Lets the pipeline engine run a tick at once, when the control plane offers it (Phase 6 engine)."""
    wake = getattr(plane, "wake_pipeline", None)
    if wake is not None:
        result = wake()
        if inspect.isawaitable(result):
            await result


async def _campaign_or_404(stores: AssuranceStores, campaign_id: str) -> CampaignRecord:
    campaign = await _run(stores.campaigns.get_campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"no campaign {campaign_id}")
    return campaign


def _classes_of(stores: AssuranceStores, campaign_id: str) -> List[dict]:
    return classes_view(stores.cases.list_classes(campaign_id), stores.results.coverage(campaign_id))


def campaign_router(stores: AssuranceStores, plane: ControlPlane) -> APIRouter:
    router = APIRouter()
    router.include_router(_create_routes(stores, plane))
    router.include_router(_campaign_routes(stores))
    router.include_router(_case_routes(stores, plane))
    router.include_router(_output_routes(stores))
    router.include_router(_result_routes(stores))
    router.include_router(_control_routes(stores))
    return router


def _create_routes(stores: AssuranceStores, plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    def create(request: CreateRequest, artifacts: Any) -> tuple:
        validated = _validated_config(request.text, artifacts, stores, attended=request.kind == CampaignKind.WORKBENCH)
        # Pin what this control node expects now. Without a listing yet the campaign has none and the engine pins it at start
        pinned = plane.expected.current() or {}
        campaign = stores.campaigns.create_campaign(
            request.name or validated.config.name,
            validated.config_json,
            validated.config_hash,
            validated.classes,
            pinned_fingerprints=pinned,
            desired_state=CampaignDesiredState.RUNNING if request.start else CampaignDesiredState.PAUSED,
            kind=request.kind,
            origin=request.origin,
        )
        return campaign, validated.config_json

    def rows(states, kinds, origins, q: Optional[str], limit: int, offset: int) -> tuple:
        with stores.transaction() as session:
            campaigns = stores.campaigns.list_campaigns(states, limit, offset, kinds=kinds, origins=origins, q=q, session=session)
            total = stores.campaigns.count_campaigns(states, kinds=kinds, origins=origins, q=q, session=session)
            ids = [campaign.campaign_id for campaign in campaigns]
            configs = stores.campaigns.current_configs(ids, session=session)
            totals = stores.campaigns.campaign_totals(ids, session=session)
        return [campaign_row_view(campaign, configs[campaign.campaign_id].config if campaign.campaign_id in configs else None, totals[campaign.campaign_id]) for campaign in campaigns], total

    @router.post(CAMPAIGNS_PATH + "/validate")
    async def validate_campaign(request: Request, name: Optional[str] = None, start: Optional[bool] = None, kind: Optional[str] = None, origin: Optional[str] = None) -> dict:
        wanted = await _request_config(request, name, start, kind, origin)
        return validated_campaign_view(await _run(_validated_config, wanted.text, _artifact_store(request), stores, wanted.kind == CampaignKind.WORKBENCH))

    @router.post(CAMPAIGNS_PATH)
    async def create_campaign(request: Request, response: Response, name: Optional[str] = None, start: Optional[bool] = None, kind: Optional[str] = None, origin: Optional[str] = None) -> dict:
        wanted = await _request_config(request, name, start, kind, origin)
        try:
            campaign, config = await _run(create, wanted, _artifact_store(request))
        except ValueError as error:  # the store refuses an origin of the other kind; _kind_and_origin has checked it already
            raise _config_problem([str(error)])
        _announce(request, campaign.campaign_id)
        await _wake_pipeline(plane)
        response.status_code = 201
        return campaign_detail_view(campaign, await _run(_classes_of, stores, campaign.campaign_id), config)

    @router.get(CAMPAIGNS_PATH)
    async def list_campaigns(
        response: Response,
        state: Optional[List[CampaignActualState]] = Query(None),
        kind: Optional[List[CampaignKind]] = Query(None),
        origin: Optional[List[CampaignOrigin]] = Query(None),
        q: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        listed, total = await _run(rows, state, kind, origin, q or None, _page(limit), max(0, offset))
        _with_total(response, total)
        return listed

    return router


def _campaign_routes(stores: AssuranceStores) -> APIRouter:
    router = APIRouter()

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}")
    async def get_campaign(campaign_id: str) -> dict:
        campaign = await _campaign_or_404(stores, campaign_id)
        configs = await _run(stores.campaigns.current_configs, [campaign_id])
        config = configs[campaign_id].config if campaign_id in configs else None
        return campaign_detail_view(campaign, await _run(_classes_of, stores, campaign_id), config)

    @router.delete(CAMPAIGNS_PATH + "/{campaign_id}", status_code=204)
    async def delete_campaign(request: Request, campaign_id: str) -> Response:
        try:
            await _run(stores.campaigns.delete_campaign, campaign_id)
        except UnknownCampaign:
            raise HTTPException(status_code=404, detail=f"no campaign {campaign_id}")
        except CampaignStateConflict as error:
            raise HTTPException(status_code=409, detail=str(error))
        topic = _campaigns_topic(request)
        if topic is not None:
            topic.campaign_deleted(campaign_id)
        return Response(status_code=204)

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/fecs")
    async def get_fecs(campaign_id: str) -> list:
        await _campaign_or_404(stores, campaign_id)
        return await _run(_classes_of, stores, campaign_id)

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/events")
    async def list_events(response: Response, campaign_id: str, after: int = 0, limit: int = 100, newest: Optional[int] = Query(None, ge=1, le=NEWEST_EVENTS_MAX)) -> list:
        await _campaign_or_404(stores, campaign_id)
        # newest: the newest events after `after`, oldest first; limit does not apply then
        events = await _run(partial(stores.campaigns.list_events, campaign_id, max(0, after), newest or _page(limit), newest=newest is not None))
        _with_total(response, await _run(stores.campaigns.count_events, campaign_id, max(0, after)))
        return [event_view(event) for event in events]

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/config")
    async def get_config(campaign_id: str) -> dict:
        campaign = await _campaign_or_404(stores, campaign_id)
        versions = await _run(stores.campaigns.config_versions, campaign_id)
        return {"current_version": campaign.config_version, "versions": [config_version_view(version) for version in versions]}

    return router


def _case_routes(stores: AssuranceStores, plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/cases")
    async def list_cases(
        response: Response,
        campaign_id: str,
        fec_id: Optional[str] = None,
        state: Optional[List[CaseState]] = Query(None),
        stage: Optional[List[PipelineStage]] = Query(None),
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        await _campaign_or_404(stores, campaign_id)
        cases = await _run(stores.cases.list_cases, campaign_id, fec_id, state, stage, _page(limit), max(0, offset))
        _with_total(response, await _run(stores.cases.count_cases, campaign_id, state, class_id=fec_id, stages=stage))
        return [case_view(case) for case in cases]

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/cases/{case_id}")
    async def get_case(campaign_id: str, case_id: int) -> dict:
        case = await _run(stores.cases.get_case, case_id)
        if case is None or case.campaign_id != campaign_id:
            raise HTTPException(status_code=404, detail=f"no case {case_id} in campaign {campaign_id}")

        def gather() -> dict:
            links = stores.pipeline.pipeline_jobs_of_case(case_id)
            return {
                **case_view(case),
                "progress": case.progress,
                "jobs": [case_job_view(link, None if link.job_id is None else plane.jobs.get(link.job_id)) for link in links],
                "run_records": [run_record_view(record) for record in stores.results.list_run_records(campaign_id, case_id=case_id, limit=None)],
                "verdicts": [verdict_view(verdict) for verdict in stores.results.list_verdicts(campaign_id, case_id=case_id, limit=None)],
            }

        return await _run(gather)

    return router


def _output_routes(stores: AssuranceStores) -> APIRouter:
    router = APIRouter()

    async def step_of_campaign(campaign_id: str, step: str, explored: bool = False) -> tuple:
        """The verdict step and the current config of a campaign for a step it runs; 404 for no campaign, 422 for a step it does not run.

        explored: the step may be the design space exploration, which has no verdict step (None).
        """
        await _campaign_or_404(stores, campaign_id)
        kind = None if explored else _step_kind(step)
        configs = await _run(stores.campaigns.current_configs, [campaign_id])
        config = configs[campaign_id].config if campaign_id in configs else {}
        if step not in (config.get("steps") or DEFAULT_STEP_NAMES):
            raise HTTPException(status_code=422, detail=f"campaign {campaign_id} does not run {step}")
        return kind, config

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/outputs")
    async def list_outputs(
        response: Response,
        campaign_id: str,
        step: str,
        state: Optional[List[CaseState]] = Query(None),
        fec_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        kind, _config = await step_of_campaign(campaign_id, step, explored=step == EXPLORATION_STEP_NAME)

        def read_explored() -> tuple:
            with stores.transaction() as session:
                return stores.cases.list_explored(campaign_id, _page(limit), max(0, offset), session=session), stores.cases.count_explored(campaign_id, session=session)

        if kind is None:
            explored_fecs, total = await _run(read_explored)
            _with_total(response, total)
            return [output_view(output) for output in explored_fecs]

        def read() -> tuple:
            with stores.transaction() as session:
                outputs = stores.cases.list_outputs(campaign_id, kind, state, fec_id, _page(limit), max(0, offset), session=session)
                total = stores.cases.count_outputs(campaign_id, kind, state, fec_id, session=session)
                sources = source_campaigns(outputs)
                existing = set(stores.campaigns.current_configs(sorted(sources), session=session)) if sources else set()
            return outputs, total, existing

        outputs, total, existing = await _run(read)
        _with_total(response, total)
        return [output_view(output, existing.__contains__) for output in outputs]

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/findings")
    async def get_findings(campaign_id: str, step: str) -> dict:
        kind, config = await step_of_campaign(campaign_id, step)
        findings = await _run(stores.results.findings, campaign_id, kind, config_monitored(config, step))
        return findings_view(step, findings)

    return router


def _result_routes(stores: AssuranceStores) -> APIRouter:
    router = APIRouter()

    def csv_rows(campaign_id: str, filters: tuple, step: Optional[StepKind], limit: Optional[int], offset: int, sort: VerdictSort = "fec_id", descending: bool = False) -> Iterator[str]:
        """The verdict CSV in pages, so a campaign of any size streams in constant memory."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(VERDICT_COLUMNS)
        position, remaining = offset, limit
        while remaining is None or remaining > 0:
            size = CSV_PAGE if remaining is None else min(CSV_PAGE, remaining)
            page = stores.results.list_verdicts(campaign_id, *filters, size, position, step=step, sort=sort, descending=descending)
            for verdict in page:
                writer.writerow(verdict_row(verdict))
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()
            position += len(page)
            if remaining is not None:
                remaining -= len(page)
            if len(page) < size:
                return

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/verdicts")
    async def list_verdicts(
        response: Response,
        campaign_id: str,
        fec_id: Optional[str] = None,
        state: Optional[VerdictState] = None,
        run_index: Optional[int] = None,
        sensitive: Optional[bool] = None,
        step: Optional[StepKind] = None,
        sort: VerdictSort = "fec_id",
        order: Literal["asc", "desc"] = "asc",
        limit: Optional[int] = None,
        offset: int = 0,
        format: str = "json",
    ):
        await _campaign_or_404(stores, campaign_id)
        if format not in ("json", "csv"):
            raise HTTPException(status_code=422, detail="format is json or csv")
        filters = (fec_id, None, state, run_index, sensitive)  # FEC, case, state, run, sensitivity: the case filter is not offered here
        descending = order == "desc"
        total = await _run(partial(stores.results.count_verdicts, campaign_id, state, class_id=fec_id, run_index=run_index, sensitive=sensitive, step=step))
        _with_total(response, total)
        if format == "json":
            verdicts = await _run(partial(stores.results.list_verdicts, campaign_id, *filters, _page(100 if limit is None else limit), max(0, offset), step=step, sort=sort, descending=descending))
            return [verdict_view(verdict) for verdict in verdicts]
        headers = {"Content-Disposition": f'attachment; filename="monitor-summaries-{campaign_id}.csv"', TOTAL_COUNT_HEADER: str(total)}
        return StreamingResponse(csv_rows(campaign_id, filters, step, limit, max(0, offset), sort, descending), media_type="text/csv", headers=headers)

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/run-records")
    async def list_run_records(response: Response, campaign_id: str, fec_id: Optional[str] = None, run_index: Optional[int] = None, limit: int = 100, offset: int = 0) -> list:
        await _campaign_or_404(stores, campaign_id)
        records = await _run(stores.results.list_run_records, campaign_id, fec_id, None, run_index, _page(limit), max(0, offset))
        _with_total(response, await _run(stores.results.count_run_records, campaign_id, fec_id, None, run_index))
        return [run_record_view(record) for record in records]

    return router


def _control_routes(stores: AssuranceStores) -> APIRouter:
    router = APIRouter()

    @router.post(CAMPAIGNS_PATH + "/{campaign_id}/{control}")
    async def control_campaign(request: Request, campaign_id: str, control: str) -> dict:
        state = CONTROLS.get(control)
        if state is None:
            raise HTTPException(status_code=404, detail=f"no control {control}; use {', '.join(CONTROLS)}")
        try:
            campaign = await _run(stores.campaigns.set_desired_state, campaign_id, state)
        except UnknownCampaign:
            raise HTTPException(status_code=404, detail=f"no campaign {campaign_id}")
        except CampaignStateConflict as error:
            raise HTTPException(status_code=409, detail=str(error))
        _announce(request, campaign_id)
        return campaign_view(campaign)

    return router
