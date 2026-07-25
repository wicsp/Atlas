from __future__ import annotations

from atlas.content.models import ResourceRecord
from atlas.content.service import ContentService
from atlas.work.service import WorkService
from atlas.workflows.models import WorkflowInvocationCreate
from atlas.workflows.service import WorkflowService

from .models import PaperAcceptResponse

PAPER_LIBRARY_PROJECT_ID = "paper-library"
PREVIEW_PROFILE_ID = "paper-preview-v1"
FULLTEXT_PROFILE_ID = "paper-fulltext-v1"
ACTIVE_RUN_STATUSES = {"blocked", "pending", "claimed"}


class UnsupportedPaperAcceptError(ValueError):
    """Raised when a Resource cannot be accepted as a paper preview."""


class PaperService:
    def __init__(
        self,
        content: ContentService,
        work: WorkService,
        workflows: WorkflowService,
    ) -> None:
        self._content = content
        self._work = work
        self._workflows = workflows

    def accept(self, resource_id: str) -> PaperAcceptResponse:
        preview = self._content.get_resource(resource_id)
        source = self._content.get_source(preview.source_id)
        if (
            preview.kind != "summary"
            or preview.metadata.get("profile_id") != PREVIEW_PROFILE_ID
            or preview.metadata.get("basis") != "abstract"
            or source.kind != "paper"
        ):
            raise UnsupportedPaperAcceptError(
                "Paper acceptance requires an abstract-based paper-preview-v1 Resource"
            )
        arxiv_id = source.external_ids.get("arxiv_id")
        if not isinstance(arxiv_id, str) or not arxiv_id.strip():
            raise UnsupportedPaperAcceptError("Paper Source has no arXiv identifier")

        fulltext = self._find_fulltext(preview.source_id)
        if fulltext is not None:
            return PaperAcceptResponse(
                reused=True,
                fulltext_resource=fulltext,
            )

        invocation = self._active_invocation(resource_id)
        if invocation is not None:
            return PaperAcceptResponse(invocation=invocation, reused=True)

        invocation = self._workflows.invoke(
            WorkflowInvocationCreate(
                workflow_name="paper.accept",
                workflow_version="1",
                input={
                    "source_id": preview.source_id,
                    "preview_resource_id": preview.resource_id,
                    "arxiv_id": arxiv_id.strip(),
                    "canonical_uri": source.canonical_uri,
                },
            )
        )
        return PaperAcceptResponse(invocation=invocation, reused=False)

    def _find_fulltext(self, source_id: str) -> ResourceRecord | None:
        return next(
            (
                resource
                for resource in self._content.list_resources(
                    source_id=source_id,
                    kind="summary",
                    limit=500,
                )
                if resource.metadata.get("profile_id") == FULLTEXT_PROFILE_ID
            ),
            None,
        )

    def _active_invocation(self, preview_resource_id: str):
        for run in self._work.list_runs(project_id=PAPER_LIBRARY_PROJECT_ID, limit=500):
            workflow_input = run.input.get("workflow_input")
            if (
                run.status in ACTIVE_RUN_STATUSES
                and isinstance(workflow_input, dict)
                and workflow_input.get("preview_resource_id") == preview_resource_id
                and run.workflow_invocation_id
            ):
                return self._workflows.get_invocation(run.workflow_invocation_id)
        return None
