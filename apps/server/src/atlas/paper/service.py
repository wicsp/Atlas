from __future__ import annotations

from atlas.content.models import ResourceRecord, ResourceReviewUpdate
from atlas.content.service import ContentService
from atlas.work.service import WorkService
from atlas.workflows.models import WorkflowInvocationCreate
from atlas.workflows.service import WorkflowService

from .models import PaperFulltextResponse, PaperIngestResponse

PAPER_LIBRARY_PROJECT_ID = "paper-library"
PREVIEW_PROFILE_ID = "paper-preview-v1"
FULLTEXT_PROFILE_ID = "paper-fulltext-v1"
ACTIVE_RUN_STATUSES = {"blocked", "pending", "claimed"}


class UnsupportedPaperIngestError(ValueError):
    """Raised when a Source cannot be ingested as a paper."""


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

    def ingest(self, source_id: str) -> PaperIngestResponse:
        """Ingest a paper Source: import to Zotero and create abstract-based preview."""
        source = self._content.get_source(source_id)
        if source.kind != "paper":
            raise UnsupportedPaperIngestError("Ingest requires a paper Source")
        arxiv_id = source.external_ids.get("arxiv_id")
        if not isinstance(arxiv_id, str) or not arxiv_id.strip():
            raise UnsupportedPaperIngestError("Paper Source has no arXiv identifier")

        existing_preview = self._find_preview(source_id)
        if existing_preview is not None:
            return PaperIngestResponse(
                reused=True,
                preview_resource=existing_preview,
            )

        invocation = self._active_ingest(source_id)
        if invocation is not None:
            return PaperIngestResponse(invocation=invocation, reused=True)

        invocation = self._workflows.invoke(
            WorkflowInvocationCreate(
                workflow_name="paper.ingest",
                workflow_version="1",
                input={
                    "source_id": source_id,
                    "arxiv_id": arxiv_id.strip(),
                    "canonical_uri": source.canonical_uri,
                },
            )
        )
        return PaperIngestResponse(invocation=invocation, reused=False)

    def fulltext(self, source_id: str, preview_resource_id: str) -> PaperFulltextResponse:
        """Generate full-text summary, replacing/upgrading the preview resource."""
        source = self._content.get_source(source_id)
        if source.kind != "paper":
            raise UnsupportedPaperIngestError("Full-text processing requires a paper Source")
        arxiv_id = source.external_ids.get("arxiv_id")
        if not isinstance(arxiv_id, str) or not arxiv_id.strip():
            raise UnsupportedPaperIngestError("Paper Source has no arXiv identifier")
        try:
            preview = self._content.get_resource(preview_resource_id)
        except KeyError as exc:
            raise UnsupportedPaperIngestError("Paper preview Resource was not found") from exc
        if preview.source_id != source_id:
            raise UnsupportedPaperIngestError(
                "Paper preview Resource does not belong to the requested Source"
            )
        if (
            preview.kind != "summary"
            or preview.metadata.get("profile_id") != PREVIEW_PROFILE_ID
        ):
            raise UnsupportedPaperIngestError(
                "Full-text processing requires a paper-preview-v1 summary Resource"
            )

        existing_fulltext = self._find_fulltext(source_id, preview_resource_id)
        if existing_fulltext is not None:
            return PaperFulltextResponse(
                reused=True,
                fulltext_resource=existing_fulltext,
            )

        invocation = self._active_fulltext(source_id, preview_resource_id)
        if invocation is not None:
            return PaperFulltextResponse(invocation=invocation, reused=True)

        invocation = self._workflows.invoke(
            WorkflowInvocationCreate(
                workflow_name="paper.fulltext",
                workflow_version="1",
                input={
                    "source_id": source_id,
                    "preview_resource_id": preview_resource_id,
                    "arxiv_id": arxiv_id.strip(),
                    "canonical_uri": source.canonical_uri,
                },
            )
        )
        return PaperFulltextResponse(invocation=invocation, reused=False)

    def _find_preview(self, source_id: str) -> ResourceRecord | None:
        for resource in self._content.list_resources(
            source_id=source_id,
            kind="summary",
            limit=500,
        ):
            if resource.metadata.get("profile_id") != PREVIEW_PROFILE_ID:
                continue
            if self._usable_preview(resource):
                return resource
            if resource.review_status != "dismissed":
                self._content.update_resource_review(
                    resource.resource_id,
                    ResourceReviewUpdate(review_status="dismissed"),
                )
        return None

    def _usable_preview(self, resource: ResourceRecord) -> bool:
        try:
            content = self._work.get_artifact_content(resource.artifact_id).content
        except KeyError:
            return False
        required = (
            "## 一句话结论",
            "## 研究问题",
            "## 方法思路",
            "## 作者声称的结果",
        )
        invalid = (
            "metadata_json",
            "{abstract}",
            "{preview_text}",
            "请提供元数据",
            "请提供摘要",
            "缺少论文信息",
        )
        lowered = content.lower()
        return all(section in content for section in required) and not any(
            marker in lowered for marker in invalid
        )

    def _find_fulltext(
        self, source_id: str, preview_resource_id: str
    ) -> ResourceRecord | None:
        return next(
            (
                resource
                for resource in self._content.list_resources(
                    source_id=source_id,
                    kind="summary",
                    limit=500,
                )
                if resource.metadata.get("profile_id") == FULLTEXT_PROFILE_ID
                and resource.metadata.get("source_preview_resource_id")
                == preview_resource_id
            ),
            None,
        )

    def _active_ingest(self, source_id: str):
        for run in self._work.list_runs(project_id=PAPER_LIBRARY_PROJECT_ID, limit=500):
            workflow_input = run.input.get("workflow_input")
            if (
                run.status in ACTIVE_RUN_STATUSES
                and isinstance(workflow_input, dict)
                and workflow_input.get("source_id") == source_id
                and run.workflow_invocation_id
            ):
                invocation = self._workflows.get_invocation(run.workflow_invocation_id)
                if (
                    invocation is not None
                    and invocation.status == "running"
                    and invocation.workflow_name == "paper.ingest"
                ):
                    return invocation
        return None

    def _active_fulltext(self, source_id: str, preview_resource_id: str):
        for run in self._work.list_runs(project_id=PAPER_LIBRARY_PROJECT_ID, limit=500):
            workflow_input = run.input.get("workflow_input")
            if (
                run.status in ACTIVE_RUN_STATUSES
                and isinstance(workflow_input, dict)
                and workflow_input.get("source_id") == source_id
                and workflow_input.get("preview_resource_id") == preview_resource_id
                and run.workflow_invocation_id
            ):
                invocation = self._workflows.get_invocation(run.workflow_invocation_id)
                if (
                    invocation is not None
                    and invocation.status == "running"
                    and invocation.workflow_name == "paper.fulltext"
                ):
                    return invocation
        return None
