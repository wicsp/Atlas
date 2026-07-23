from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import __version__
from .agents.models import (
    AgentRecord,
    AgentRegistration,
    AgentRegistrationResponse,
    RunnerRecord,
    RunnerRegistration,
    RunnerRegistrationResponse,
)
from .agents.service import AgentService, create_agent_service
from .config import Settings, get_settings
from .content.models import (
    CommentRecord,
    KnowledgeRefCreate,
    KnowledgeRefRecord,
    ResourceKind,
    ResourceRecord,
    ResourceReviewUpdate,
    ReviewStatus,
    SourceKind,
    SourceRecord,
    SourceUpsert,
)
from .content.service import ContentService, create_content_service
from .dashboard import DashboardSnapshot, DashboardSnapshotCollector
from .messages.models import MessageAck, MessageClaim, MessageCreate, MessageRecord
from .messages.service import MessageService, MessageStateError, create_message_service
from .network import NetworkConnectivity
from .probes import ProbeHistorySummary, ProbeResult
from .rate_limit import login_rate_limiter
from .review.ignore import (
    ResourceIgnoreService,
    create_resource_ignore_service,
)
from .review.models import (
    CommentCompleteRequest,
    CommentCompleteResponse,
    CommentRequest,
    CommentRequestResponse,
    CommentSyncRequestResponse,
    ComparisonRequestResponse,
    ResourceIgnoreRequest,
    ResourceIgnoreResponse,
)
from .review.service import (
    ResourceAlreadyCommentedError,
    ReviewService,
    UnsupportedReviewResourceError,
)
from .scheduling.models import ScheduleRecord
from .scheduling.service import ScheduleCoordinator, create_schedule_coordinator
from .security import (
    SESSION_COOKIE_NAME,
    create_session_token,
    verify_agent_token,
    verify_login_password,
    verify_session_token,
)
from .sub2api import (
    Sub2ApiAccountsResponse,
    Sub2ApiRefreshResponse,
    Sub2ApiSnapshotCollector,
    get_sub2api_accounts,
)
from .system import (
    GpuSummary,
    SystemGlanceSummary,
    SystemSummary,
    get_system_summary,
)
from .todos import (
    DEFAULT_TODO_STORE_PATH,
    TodoCreateRequest,
    TodoItem,
    TodoNotFoundError,
    TodoUpdateRequest,
    create_todo,
    delete_todo,
    list_todos,
    update_todo,
)
from .work.models import (
    ArtifactContentRecord,
    ArtifactContentUpsert,
    ArtifactRef,
    EventRecord,
    ExecutionAttemptRecord,
    HeartbeatCreate,
    ProjectCreate,
    ProjectRecord,
    RunCancel,
    RunComplete,
    RunCreate,
    RunFail,
    RunRecord,
    RunStatus,
)
from .work.service import WorkService, create_work_service
from .workflows.models import (
    WorkflowDefinitionCreate,
    WorkflowDefinitionRecord,
    WorkflowInvocationCreate,
    WorkflowInvocationRecord,
)
from .workflows.service import WorkflowService, create_workflow_service


class HealthResponse(BaseModel):
    status: str
    version: str


class LoginRequest(BaseModel):
    password: str


class AuthStatus(BaseModel):
    authenticated: bool


class DeleteResponse(BaseModel):
    deleted: bool


class ResourceBundle(BaseModel):
    resource: ResourceRecord
    source: SourceRecord
    artifact: ArtifactRef


class ResourceDocument(ResourceBundle):
    content: str


def _todo_store_path(request: Request) -> Path:
    return request.app.state.todo_store_path


def _dashboard_collector(request: Request) -> DashboardSnapshotCollector:
    return request.app.state.dashboard_collector


def _agent_service(request: Request) -> AgentService:
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        settings: Settings = request.app.state.settings
        service = create_agent_service(
            database_path=settings.agents.database_path,
            heartbeat_ttl_seconds=settings.agents.heartbeat_ttl_seconds,
        )
        request.app.state.agent_service = service
    return service


def _message_service(request: Request) -> MessageService:
    service = getattr(request.app.state, "message_service", None)
    if service is None:
        settings: Settings = request.app.state.settings
        service = create_message_service(settings.agents.database_path)
        request.app.state.message_service = service
    return service

def _work_service(request: Request) -> WorkService:
    service = getattr(request.app.state, "work_service", None)
    if service is None:
        settings: Settings = request.app.state.settings
        service = create_work_service(
            database_path=settings.work.database_path,
            lease_ttl_seconds=settings.work.lease_ttl_seconds,
        )
        request.app.state.work_service = service
    return service


def _workflow_service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        settings: Settings = request.app.state.settings
        service = create_workflow_service(
            settings.work.database_path,
            _work_service(request),
        )
        request.app.state.workflow_service = service
    return service


def _content_service(request: Request) -> ContentService:
    service = getattr(request.app.state, "content_service", None)
    if service is None:
        settings: Settings = request.app.state.settings
        service = create_content_service(settings.work.database_path)
        request.app.state.content_service = service
    return service


def _schedule_coordinator(request: Request) -> ScheduleCoordinator:
    coordinator = getattr(request.app.state, "schedule_coordinator", None)
    if coordinator is None:
        settings: Settings = request.app.state.settings
        coordinator = create_schedule_coordinator(
            settings.work.database_path,
            _work_service(request),
            _workflow_service(request),
            _content_service(request),
            settings.scheduler.poll_interval_seconds,
        )
        request.app.state.schedule_coordinator = coordinator
    return coordinator


def _review_service(request: Request) -> ReviewService:
    return ReviewService(
        content=_content_service(request),
        work=_work_service(request),
    )


def _resource_ignore_service(request: Request) -> ResourceIgnoreService:
    service = getattr(request.app.state, "resource_ignore_service", None)
    if service is None:
        settings: Settings = request.app.state.settings
        service = create_resource_ignore_service(
            settings.work.database_path,
            _work_service(request),
        )
        request.app.state.resource_ignore_service = service
    return service


def require_auth(request: Request) -> None:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not verify_session_token(token, settings.auth):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )


def require_agent_auth(request: Request) -> None:
    settings: Settings = request.app.state.settings
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not verify_agent_token(token, settings.agents):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent token required",
        )


def require_scoped_agent_auth(request: Request) -> AgentRecord:
    """Resolve the authenticated agent from their scoped credential."""
    settings: Settings = request.app.state.settings
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )
    service = _agent_service(request)
    agent = service.resolve_agent(token)
    if agent is not None:
        return agent
    if verify_agent_token(token, settings.agents):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Shared token not accepted for work operations. "
                "Register to obtain a scoped credential."
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid agent credential",
    )


def require_control_auth(request: Request) -> None:
    """Accept an operator session or the provisioned personal control credential."""
    settings: Settings = request.app.state.settings
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if verify_session_token(session_token, settings.auth):
        return

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and verify_agent_token(token, settings.agents):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Control authentication required",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    collector = getattr(app.state, "sub2api_collector", None)
    dashboard_collector = getattr(app.state, "dashboard_collector", None)
    schedule_coordinator = getattr(app.state, "schedule_coordinator", None)
    if collector is not None:
        collector.start()
    if dashboard_collector is not None:
        dashboard_collector.start()
    if schedule_coordinator is not None:
        await schedule_coordinator.start()
    try:
        yield
    finally:
        if schedule_coordinator is not None:
            await schedule_coordinator.stop()
        if dashboard_collector is not None:
            await dashboard_collector.stop()
        if collector is not None:
            await collector.stop()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(title="Atlas", version=__version__, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.probe_results = {}
    app.state.todo_store_path = DEFAULT_TODO_STORE_PATH
    app.state.agent_service = None
    app.state.message_service = None
    app.state.work_service = None
    app.state.content_service = None
    app.state.workflow_service = None
    app.state.schedule_coordinator = None
    app.state.sub2api_collector = (
        Sub2ApiSnapshotCollector(resolved_settings.sub2api)
        if resolved_settings.sub2api.enabled
        else None
    )
    app.state.dashboard_collector = DashboardSnapshotCollector(resolved_settings)
    if resolved_settings.scheduler.enabled:
        app.state.work_service = create_work_service(
            resolved_settings.work.database_path,
            resolved_settings.work.lease_ttl_seconds,
        )
        app.state.content_service = create_content_service(resolved_settings.work.database_path)
        app.state.workflow_service = create_workflow_service(
            resolved_settings.work.database_path,
            app.state.work_service,
        )
        app.state.schedule_coordinator = create_schedule_coordinator(
            resolved_settings.work.database_path,
            app.state.work_service,
            app.state.workflow_service,
            app.state.content_service,
            resolved_settings.scheduler.poll_interval_seconds,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get(
        "/api/schedules",
        response_model=list[ScheduleRecord],
        dependencies=[Depends(require_control_auth)],
    )
    async def list_schedules(request: Request) -> list[ScheduleRecord]:
        return _schedule_coordinator(request).list_schedules()

    @app.post("/api/auth/login", response_model=AuthStatus)
    async def login(payload: LoginRequest, request: Request, response: Response) -> AuthStatus:
        client_ip = login_rate_limiter.check(request)
        app_settings: Settings = request.app.state.settings
        if not app_settings.auth.password_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin password is not configured",
            )
        if not verify_login_password(payload.password, app_settings.auth):
            login_rate_limiter.record_failure(client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )

        login_rate_limiter.record_success(client_ip)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=create_session_token(app_settings.auth.session_secret),
            max_age=app_settings.auth.session_max_age_seconds,
            httponly=True,
            secure=app_settings.auth.cookie_secure,
            samesite="lax",
        )
        return AuthStatus(authenticated=True)

    @app.post("/api/auth/logout", response_model=AuthStatus)
    async def logout(response: Response) -> AuthStatus:
        response.delete_cookie(SESSION_COOKIE_NAME, httponly=True, samesite="lax")
        return AuthStatus(authenticated=False)

    @app.get("/api/auth/me", response_model=AuthStatus)
    async def me(request: Request) -> AuthStatus:
        app_settings: Settings = request.app.state.settings
        token = request.cookies.get(SESSION_COOKIE_NAME)
        return AuthStatus(authenticated=verify_session_token(token, app_settings.auth))

    @app.get(
        "/api/agents",
        response_model=list[AgentRecord],
        dependencies=[Depends(require_auth)],
    )
    async def list_agents(request: Request) -> list[AgentRecord]:
        return _agent_service(request).list_agents()

    @app.post(
        "/api/agents/register",
        response_model=AgentRegistrationResponse,
        dependencies=[Depends(require_agent_auth)],
    )
    async def register_agent(
        request: Request,
        payload: AgentRegistration,
    ) -> AgentRegistrationResponse:
        """Register an agent and return a scoped credential for work operations."""
        return _agent_service(request).register_agent(payload)

    @app.post(
        "/api/agents/{agent_id}/heartbeat",
        response_model=AgentRecord,
        dependencies=[Depends(require_agent_auth)],
    )
    async def agent_heartbeat(request: Request, agent_id: str) -> AgentRecord:
        try:
            return _agent_service(request).record_heartbeat(agent_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found",
            ) from exc

    # Runner is the runtime-neutral execution identity. The Agent endpoints above
    # remain as an atlas-agent-v3 compatibility surface for deployed clients.
    @app.get(
        "/api/runners",
        response_model=list[RunnerRecord],
        dependencies=[Depends(require_auth)],
    )
    async def list_runners(request: Request) -> list[RunnerRecord]:
        return _agent_service(request).list_runners()

    @app.post(
        "/api/runners/register",
        response_model=RunnerRegistrationResponse,
        dependencies=[Depends(require_agent_auth)],
    )
    async def register_runner(
        request: Request,
        payload: RunnerRegistration,
    ) -> RunnerRegistrationResponse:
        return _agent_service(request).register_runner(payload)

    @app.post(
        "/api/runners/{runner_id}/heartbeat",
        response_model=RunnerRecord,
        dependencies=[Depends(require_agent_auth)],
    )
    async def runner_heartbeat(request: Request, runner_id: str) -> RunnerRecord:
        try:
            return _agent_service(request).record_runner_heartbeat(runner_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Runner not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    # ── Content API (RFC 0003) ─────────────────────────────────

    @app.post(
        "/api/sources",
        response_model=SourceRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def upsert_source(request: Request, payload: SourceUpsert) -> SourceRecord:
        try:
            return _content_service(request).upsert_source(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.get(
        "/api/sources",
        response_model=list[SourceRecord],
        dependencies=[Depends(require_control_auth)],
    )
    async def list_sources(
        request: Request,
        kind: SourceKind | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[SourceRecord]:
        return _content_service(request).list_sources(kind=kind, limit=limit)

    @app.get(
        "/api/sources/{source_id}",
        response_model=SourceRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def get_source(request: Request, source_id: str) -> SourceRecord:
        try:
            return _content_service(request).get_source(source_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source not found",
            ) from exc

    @app.get(
        "/api/resources",
        response_model=list[ResourceRecord],
        dependencies=[Depends(require_control_auth)],
    )
    async def list_resources(
        request: Request,
        source_id: str | None = None,
        kind: ResourceKind | None = None,
        review_status: ReviewStatus | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[ResourceRecord]:
        return _content_service(request).list_resources(
            source_id=source_id,
            kind=kind,
            review_status=review_status,
            limit=limit,
        )

    @app.get(
        "/api/resources/{resource_id}",
        response_model=ResourceRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def get_resource(request: Request, resource_id: str) -> ResourceRecord:
        try:
            return _content_service(request).get_resource(resource_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc

    @app.get(
        "/api/resources/{resource_id}/bundle",
        response_model=ResourceBundle,
        dependencies=[Depends(require_control_auth)],
    )
    async def get_resource_bundle(request: Request, resource_id: str) -> ResourceBundle:
        try:
            resource = _content_service(request).get_resource(resource_id)
            source = _content_service(request).get_source(resource.source_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource or Source not found",
            ) from exc
        artifact = next(
            (
                candidate
                for candidate in _work_service(request).list_artifacts(
                    resource.produced_by_run_id
                )
                if candidate.artifact_id == resource.artifact_id
            ),
            None,
        )
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resource artifact reference is missing",
            )
        return ResourceBundle(resource=resource, source=source, artifact=artifact)

    @app.get(
        "/api/resources/{resource_id}/content",
        response_model=ResourceDocument,
        dependencies=[Depends(require_control_auth)],
    )
    async def get_resource_content(request: Request, resource_id: str) -> ResourceDocument:
        bundle = await get_resource_bundle(request, resource_id)
        try:
            content = _work_service(request).get_artifact_content(bundle.artifact.artifact_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource content has not been uploaded to Atlas",
            ) from exc
        return ResourceDocument(**bundle.model_dump(), content=content.content)

    @app.put(
        "/api/artifacts/{artifact_id}/content",
        response_model=ArtifactContentRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def upsert_artifact_content(
        request: Request,
        artifact_id: str,
        payload: ArtifactContentUpsert,
    ) -> ArtifactContentRecord:
        try:
            return _work_service(request).upsert_artifact_content(
                artifact_id, payload.content
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.patch(
        "/api/resources/{resource_id}/review",
        response_model=ResourceRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def update_resource_review(
        request: Request,
        resource_id: str,
        payload: ResourceReviewUpdate,
    ) -> ResourceRecord:
        try:
            if payload.review_status == "dismissed":
                return _resource_ignore_service(request).ignore(resource_id).resource
            current = _content_service(request).get_resource(resource_id)
            if payload.review_status == "pending" and current.review_status == "dismissed":
                return _resource_ignore_service(request).restore(resource_id).resource
            return _content_service(request).update_resource_review(resource_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc

    @app.post(
        "/api/knowledge-refs",
        response_model=KnowledgeRefRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def upsert_knowledge_ref(
        request: Request,
        payload: KnowledgeRefCreate,
    ) -> KnowledgeRefRecord:
        try:
            return _content_service(request).upsert_knowledge_ref(payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Referenced record not found: {exc.args[0]}",
            ) from exc

    @app.get(
        "/api/knowledge-refs",
        response_model=list[KnowledgeRefRecord],
        dependencies=[Depends(require_control_auth)],
    )
    async def list_knowledge_refs(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[KnowledgeRefRecord]:
        return _content_service(request).list_knowledge_refs(limit=limit)

    @app.get(
        "/api/comments",
        response_model=list[CommentRecord],
        dependencies=[Depends(require_control_auth)],
    )
    async def list_comments(
        request: Request,
        resource_id: str | None = None,
        source_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[CommentRecord]:
        return _content_service(request).list_comments(
            resource_id=resource_id,
            source_id=source_id,
            limit=limit,
        )

    @app.post(
        "/api/review-actions/comment",
        response_model=CommentRequestResponse,
        dependencies=[Depends(require_control_auth)],
    )
    async def request_resource_comment(
        request: Request,
        payload: CommentRequest,
    ) -> CommentRequestResponse:
        try:
            return _review_service(request).request_comment(payload.resource_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc
        except (ResourceAlreadyCommentedError, UnsupportedReviewResourceError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/review-actions/sync-comment",
        response_model=CommentSyncRequestResponse,
        dependencies=[Depends(require_control_auth)],
    )
    async def request_comment_sync(
        request: Request,
        payload: CommentRequest,
    ) -> CommentSyncRequestResponse:
        try:
            return _review_service(request).request_comment_sync(payload.resource_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc
        except UnsupportedReviewResourceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/review-actions/complete-comment",
        response_model=CommentCompleteResponse,
        dependencies=[Depends(require_control_auth)],
    )
    async def complete_resource_comment(
        request: Request,
        payload: CommentCompleteRequest,
    ) -> CommentCompleteResponse:
        try:
            return _review_service(request).complete_comment(
                payload.resource_id,
                payload.body_markdown,
                payload.content_hash,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc
        except UnsupportedReviewResourceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/review-actions/compare",
        response_model=ComparisonRequestResponse,
        dependencies=[Depends(require_control_auth)],
    )
    async def request_resource_comparison(
        request: Request,
        payload: CommentRequest,
    ) -> ComparisonRequestResponse:
        try:
            return _review_service(request).request_comparison(payload.resource_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc
        except UnsupportedReviewResourceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/review-actions/ignore-resource",
        response_model=ResourceIgnoreResponse,
        dependencies=[Depends(require_control_auth)],
    )
    async def ignore_resource(
        request: Request,
        payload: ResourceIgnoreRequest,
    ) -> ResourceIgnoreResponse:
        try:
            return _resource_ignore_service(request).ignore(payload.resource_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc

    @app.post(
        "/api/review-actions/restore-resource",
        response_model=ResourceIgnoreResponse,
        dependencies=[Depends(require_control_auth)],
    )
    async def restore_resource(
        request: Request,
        payload: ResourceIgnoreRequest,
    ) -> ResourceIgnoreResponse:
        try:
            return _resource_ignore_service(request).restore(payload.resource_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc

    @app.post(
        "/api/messages",
        response_model=MessageRecord,
        dependencies=[Depends(require_agent_auth)],
    )
    async def send_message(request: Request, payload: MessageCreate) -> MessageRecord:
        return _message_service(request).send_message(payload)

    @app.get(
        "/api/agents/{agent_id}/messages/inbox",
        response_model=list[MessageRecord],
        dependencies=[Depends(require_agent_auth)],
    )
    async def message_inbox(request: Request, agent_id: str) -> list[MessageRecord]:
        return _message_service(request).list_inbox(agent_id)

    @app.post(
        "/api/messages/{message_id}/claim",
        response_model=MessageRecord,
        dependencies=[Depends(require_agent_auth)],
    )
    async def claim_message(
        request: Request,
        message_id: str,
        payload: MessageClaim,
    ) -> MessageRecord:
        try:
            return _message_service(request).claim_message(message_id, payload.agent_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found",
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Message belongs to another agent",
            ) from exc
        except MessageStateError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/messages/{message_id}/ack",
        response_model=MessageRecord,
        dependencies=[Depends(require_agent_auth)],
    )
    async def acknowledge_message(
        request: Request,
        message_id: str,
        payload: MessageAck,
    ) -> MessageRecord:
        try:
            return _message_service(request).acknowledge_message(
                message_id,
                agent_id=payload.agent_id,
                result=payload.result,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found",
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Message belongs to another agent",
            ) from exc
        except MessageStateError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.get(
        "/api/messages/{message_id}",
        response_model=MessageRecord,
        dependencies=[Depends(require_auth)],
    )
    async def get_message(request: Request, message_id: str) -> MessageRecord:
        try:
            return _message_service(request).get_message(message_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found",
            ) from exc


    # ── Work API (Milestone 2) ──────────────────────────────────

    @app.post(
        "/api/workflows",
        response_model=WorkflowDefinitionRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def register_workflow(
        request: Request,
        payload: WorkflowDefinitionCreate,
    ) -> WorkflowDefinitionRecord:
        try:
            return _workflow_service(request).register_definition(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.get(
        "/api/workflows",
        response_model=list[WorkflowDefinitionRecord],
        dependencies=[Depends(require_control_auth)],
    )
    async def list_workflows(request: Request) -> list[WorkflowDefinitionRecord]:
        return _workflow_service(request).list_definitions()

    @app.post(
        "/api/workflow-invocations",
        response_model=WorkflowInvocationRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def invoke_workflow(
        request: Request,
        payload: WorkflowInvocationCreate,
    ) -> WorkflowInvocationRecord:
        try:
            return _workflow_service(request).invoke(payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow definition not found",
            ) from exc

    @app.get(
        "/api/workflow-invocations/{invocation_id}",
        response_model=WorkflowInvocationRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def get_workflow_invocation(
        request: Request,
        invocation_id: str,
    ) -> WorkflowInvocationRecord:
        try:
            return _workflow_service(request).get_invocation(invocation_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow invocation not found",
            ) from exc

    @app.post(
        "/api/projects",
        response_model=ProjectRecord,
        dependencies=[Depends(require_agent_auth)],
    )
    async def create_project(request: Request, payload: ProjectCreate) -> ProjectRecord:
        return _work_service(request).create_project(payload)

    @app.get(
        "/api/projects",
        response_model=list[ProjectRecord],
        dependencies=[Depends(require_auth)],
    )
    async def list_projects(request: Request) -> list[ProjectRecord]:
        return _work_service(request).list_projects()

    @app.post(
        "/api/runs/enqueue",
        response_model=RunRecord,
        dependencies=[Depends(require_agent_auth)],
    )
    async def enqueue_run(request: Request, payload: RunCreate) -> RunRecord:
        return _work_service(request).enqueue_run(payload)

    @app.get(
        "/api/runs/next",
    )
    async def claim_next_run(
        request: Request,
        agent: Annotated[AgentRecord, Depends(require_scoped_agent_auth)],
    ):
        result = _work_service(request).claim_next(agent)
        if result is None:
            return None
        run, attempt_id, claim_token = result
        return {
            **run.model_dump(),
            "attempt_id": attempt_id,
            "claim_token": claim_token,
            "execution_context": _work_service(request).upstream_context(run),
        }

    @app.post(
        "/api/runs/{run_id}/claim",
    )
    async def claim_run(
        request: Request,
        run_id: str,
        agent: Annotated[AgentRecord, Depends(require_scoped_agent_auth)],
    ):
        try:
            result = _work_service(request).claim_by_id(run_id, agent)
            run, attempt_id, claim_token = result
            return {
                **run.model_dump(),
                "attempt_id": attempt_id,
                "claim_token": claim_token,
                "execution_context": _work_service(request).upstream_context(run),
            }
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found",
            ) from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/runs/{run_id}/heartbeat",
        response_model=RunRecord,
    )
    async def run_heartbeat(
        request: Request,
        run_id: str,
        payload: Annotated[HeartbeatCreate, Body()],
        agent: Annotated[AgentRecord, Depends(require_scoped_agent_auth)],
    ) -> RunRecord:
        try:
            return _work_service(request).heartbeat(
                run_id, agent.agent_id, payload.attempt_id, payload.claim_token
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found",
            ) from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/runs/{run_id}/complete",
        response_model=RunRecord,
    )
    async def complete_run(
        request: Request,
        run_id: str,
        payload: RunComplete,
        agent: Annotated[AgentRecord, Depends(require_scoped_agent_auth)],
    ) -> RunRecord:
        payload.agent_id = agent.agent_id
        idempotency_key = request.headers.get("Idempotency-Key")
        try:
            return _work_service(request).complete(
                run_id, payload, idempotency_key=idempotency_key
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found",
            ) from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/runs/{run_id}/fail",
        response_model=RunRecord,
    )
    async def fail_run(
        request: Request,
        run_id: str,
        payload: RunFail,
        agent: Annotated[AgentRecord, Depends(require_scoped_agent_auth)],
    ) -> RunRecord:
        payload.agent_id = agent.agent_id
        idempotency_key = request.headers.get("Idempotency-Key")
        try:
            return _work_service(request).fail(
                run_id, payload, idempotency_key=idempotency_key
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found",
            ) from exc
        except (ValueError, PermissionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/runs/{run_id}/cancel",
        response_model=RunRecord,
        dependencies=[Depends(require_auth)],
    )
    async def cancel_run(request: Request, run_id: str) -> RunRecord:
        try:
            return _work_service(request).cancel(run_id, RunCancel())
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @app.get(
        "/api/runs",
        response_model=list[RunRecord],
        dependencies=[Depends(require_control_auth)],
    )
    async def list_runs(
        request: Request,
        project_id: str | None = None,
        status_str: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        run_status: RunStatus | None = status_str if status_str else None  # type: ignore[assignment]
        return _work_service(request).list_runs(
            project_id=project_id,
            status=run_status,
            limit=limit,
        )

    @app.get(
        "/api/runs/{run_id}",
        response_model=RunRecord,
        dependencies=[Depends(require_control_auth)],
    )
    async def get_run(request: Request, run_id: str) -> RunRecord:
        try:
            return _work_service(request).get_run(run_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Run not found",
            ) from exc

    @app.get(
        "/api/runs/{run_id}/attempts",
        response_model=list[ExecutionAttemptRecord],
        dependencies=[Depends(require_auth)],
    )
    async def list_run_attempts(request: Request, run_id: str) -> list[ExecutionAttemptRecord]:
        return _work_service(request).list_attempts(run_id)

    @app.get(
        "/api/runs/{run_id}/events",
        response_model=list[EventRecord],
        dependencies=[Depends(require_auth)],
    )
    async def list_run_events(
        request: Request,
        run_id: str,
        limit: int = 200,
    ) -> list[EventRecord]:
        return _work_service(request).list_events(run_id, limit=limit)

    @app.get(
        "/api/runs/{run_id}/artifacts",
        response_model=list[ArtifactRef],
        dependencies=[Depends(require_auth)],
    )
    async def list_run_artifacts(request: Request, run_id: str) -> list[ArtifactRef]:
        return _work_service(request).list_artifacts(run_id)
    @app.get(
        "/api/system/summary",
        response_model=SystemSummary,
        dependencies=[Depends(require_auth)],
    )
    async def system_summary() -> SystemSummary:
        return get_system_summary()

    @app.get(
        "/api/dashboard/snapshot",
        response_model=DashboardSnapshot,
        dependencies=[Depends(require_auth)],
    )
    async def dashboard_snapshot(request: Request) -> DashboardSnapshot:
        collector: Sub2ApiSnapshotCollector | None = request.app.state.sub2api_collector
        return await _dashboard_collector(request).get_snapshot(collector)

    @app.get(
        "/api/system/glance",
        response_model=SystemGlanceSummary,
        dependencies=[Depends(require_auth)],
    )
    async def system_glance(request: Request) -> SystemGlanceSummary:
        return await _dashboard_collector(request).get_system()

    @app.get(
        "/api/system/gpus",
        response_model=list[GpuSummary],
        dependencies=[Depends(require_auth)],
    )
    async def system_gpus(request: Request) -> list[GpuSummary]:
        return await _dashboard_collector(request).get_gpus()

    @app.get(
        "/api/network/connectivity",
        response_model=NetworkConnectivity,
        dependencies=[Depends(require_auth)],
    )
    async def network_connectivity(request: Request) -> NetworkConnectivity:
        return await _dashboard_collector(request).get_network()

    @app.get(
        "/api/probes",
        response_model=list[ProbeResult],
        dependencies=[Depends(require_auth)],
    )
    async def list_probes(request: Request) -> list[ProbeResult]:
        return await _dashboard_collector(request).get_probes()

    @app.get(
        "/api/probes/history",
        response_model=list[ProbeHistorySummary],
        dependencies=[Depends(require_auth)],
    )
    async def probe_history(request: Request) -> list[ProbeHistorySummary]:
        return await _dashboard_collector(request).get_probe_history()

    @app.post(
        "/api/probes/run",
        response_model=list[ProbeResult],
        dependencies=[Depends(require_auth)],
    )
    async def run_configured_probes(request: Request) -> list[ProbeResult]:
        return await _dashboard_collector(request).refresh_probes()

    @app.get(
        "/api/sub2api/accounts",
        response_model=Sub2ApiAccountsResponse,
        dependencies=[Depends(require_auth)],
    )
    async def sub2api_accounts(request: Request) -> Sub2ApiAccountsResponse:
        app_settings: Settings = request.app.state.settings
        collector: Sub2ApiSnapshotCollector | None = request.app.state.sub2api_collector
        return await get_sub2api_accounts(
            app_settings.sub2api,
            refreshing=collector.refreshing if collector is not None else False,
        )

    @app.post(
        "/api/sub2api/accounts/refresh",
        response_model=Sub2ApiRefreshResponse,
        dependencies=[Depends(require_auth)],
    )
    async def refresh_sub2api_accounts(request: Request) -> Sub2ApiRefreshResponse:
        app_settings: Settings = request.app.state.settings
        collector: Sub2ApiSnapshotCollector | None = request.app.state.sub2api_collector
        if not app_settings.sub2api.enabled or collector is None:
            return Sub2ApiRefreshResponse(
                status="disabled",
                scheduled=False,
                refreshing=False,
            )

        scheduled = collector.request_refresh()
        if not collector.running:
            asyncio.create_task(collector.refresh_once())
        return Sub2ApiRefreshResponse(
            status="running" if collector.refreshing else "scheduled",
            scheduled=scheduled,
            refreshing=collector.refreshing,
        )

    @app.get(
        "/api/todos",
        response_model=list[TodoItem],
        dependencies=[Depends(require_auth)],
        deprecated=True,
    )
    async def get_todos(request: Request) -> list[TodoItem]:
        return list_todos(_todo_store_path(request))

    @app.post(
        "/api/todos",
        response_model=TodoItem,
        dependencies=[Depends(require_auth)],
        deprecated=True,
    )
    async def create_todo_item(request: Request, payload: TodoCreateRequest) -> TodoItem:
        return create_todo(payload, _todo_store_path(request))

    @app.patch(
        "/api/todos/{todo_id}",
        response_model=TodoItem,
        dependencies=[Depends(require_auth)],
        deprecated=True,
    )
    async def update_todo_item(
        request: Request,
        todo_id: str,
        payload: TodoUpdateRequest,
    ) -> TodoItem:
        try:
            return update_todo(todo_id, payload, _todo_store_path(request))
        except TodoNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Todo not found",
            ) from exc

    @app.delete(
        "/api/todos/{todo_id}",
        response_model=DeleteResponse,
        dependencies=[Depends(require_auth)],
        deprecated=True,
    )
    async def delete_todo_item(request: Request, todo_id: str) -> DeleteResponse:
        try:
            delete_todo(todo_id, _todo_store_path(request))
        except TodoNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Todo not found",
            ) from exc
        return DeleteResponse(deleted=True)

    return app


app = create_app()
