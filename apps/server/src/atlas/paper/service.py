from __future__ import annotations

import json

from atlas.content.models import ResourceRecord, ResourceReviewUpdate, SourceRecord, SourceUpdate
from atlas.content.service import ContentService
from atlas.work.service import WorkService
from atlas.workflows.models import WorkflowInvocationCreate
from atlas.workflows.service import WorkflowService

from .models import (
    PaperCitationEdge,
    PaperComparisonResponse,
    PaperFulltextResponse,
    PaperIngestResponse,
    PaperLibraryRecord,
    PaperLibraryUpdate,
)

PAPER_LIBRARY_PROJECT_ID = "paper-library"
PREVIEW_PROFILE_ID = "paper-preview-v1"
FULLTEXT_PROFILE_ID = "paper-reading-brief-v3"
FULLTEXT_WORKFLOW_VERSION = "3"
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
                workflow_version=FULLTEXT_WORKFLOW_VERSION,
                input={
                    "source_id": source_id,
                    "preview_resource_id": preview_resource_id,
                    "arxiv_id": arxiv_id.strip(),
                    "canonical_uri": source.canonical_uri,
                },
            )
        )
        return PaperFulltextResponse(invocation=invocation, reused=False)

    def update_library(
        self,
        source_id: str,
        payload: PaperLibraryUpdate,
    ) -> PaperLibraryRecord:
        source = self._paper_source(source_id)
        if source_id in payload.citation_source_ids:
            raise ValueError("a paper cannot cite itself")
        for cited_source_id in payload.citation_source_ids:
            self._paper_source(cited_source_id)
        source = self._content.update_source(
            SourceUpdate(
                source_id=source_id,
                metadata={
                    "paper_tags": payload.tags,
                    "paper_categories": payload.categories,
                    "paper_citation_source_ids": payload.citation_source_ids,
                },
            )
        )
        return self._library_record(source)

    def search_library(
        self,
        query: str | None = None,
        tag: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[PaperLibraryRecord]:
        query_text = (query or "").strip().casefold()
        tag_text = (tag or "").strip().casefold()
        category_text = (category or "").strip().casefold()
        matches: list[PaperLibraryRecord] = []
        for source in self._content.list_sources(kind="paper", limit=500):
            record = self._library_record(source)
            if tag_text and tag_text not in {item.casefold() for item in record.tags}:
                continue
            if category_text and category_text not in {
                item.casefold() for item in record.categories
            }:
                continue
            haystack = " ".join(
                [
                    source.title or "",
                    source.canonical_uri,
                    json.dumps(source.external_ids, ensure_ascii=False),
                    " ".join(record.tags),
                    " ".join(record.categories),
                    self._atlas_text_for_source(source.source_id),
                ]
            ).casefold()
            if query_text and query_text not in haystack:
                continue
            matches.append(record)
            if len(matches) >= limit:
                break
        return matches

    def compare_library(self, source_ids: list[str]) -> PaperComparisonResponse:
        papers = [self._library_record(self._paper_source(source_id)) for source_id in source_ids]
        shared_tags = _shared_labels([paper.tags for paper in papers])
        shared_categories = _shared_labels([paper.categories for paper in papers])
        selected = set(source_ids)
        edges = [
            PaperCitationEdge(
                citing_source_id=paper.source.source_id,
                cited_source_id=cited_source_id,
            )
            for paper in papers
            for cited_source_id in paper.citation_source_ids
            if cited_source_id in selected
        ]
        return PaperComparisonResponse(
            papers=papers,
            shared_tags=shared_tags,
            shared_categories=shared_categories,
            citation_edges=edges,
        )

    def _paper_source(self, source_id: str) -> SourceRecord:
        source = self._content.get_source(source_id)
        if source.kind != "paper":
            raise UnsupportedPaperIngestError("Paper library operations require a paper Source")
        return source

    def _library_record(self, source: SourceRecord) -> PaperLibraryRecord:
        resources = [
            resource
            for resource in self._content.list_resources(
                source_id=source.source_id,
                kind="summary",
                limit=500,
            )
            if resource.review_status != "dismissed"
        ]
        excerpt = None
        for resource in resources:
            try:
                excerpt = self._work.get_artifact_content(resource.artifact_id).content[:4000]
                break
            except KeyError:
                continue
        return PaperLibraryRecord(
            source=source,
            tags=_metadata_labels(source.metadata.get("paper_tags")),
            categories=_metadata_labels(source.metadata.get("paper_categories")),
            citation_source_ids=_metadata_source_ids(
                source.metadata.get("paper_citation_source_ids")
            ),
            summary_resource_ids=[resource.resource_id for resource in resources],
            summary_excerpt=excerpt,
        )

    def _atlas_text_for_source(self, source_id: str) -> str:
        chunks: list[str] = []
        total_bytes = 0
        for run in self._work.list_runs(project_id=PAPER_LIBRARY_PROJECT_ID, limit=500):
            workflow_input = run.input.get("workflow_input")
            if not isinstance(workflow_input, dict):
                workflow_input = run.input
            if workflow_input.get("source_id") != source_id:
                continue
            for artifact in self._work.list_artifacts(run.run_id):
                try:
                    content = self._work.get_artifact_content(artifact.artifact_id).content
                except KeyError:
                    continue
                encoded = content.encode()
                remaining = 2 * 1024 * 1024 - total_bytes
                if remaining <= 0:
                    return "\n".join(chunks)
                if len(encoded) > remaining:
                    content = encoded[:remaining].decode(errors="ignore")
                    encoded = content.encode()
                chunks.append(content)
                total_bytes += len(encoded)
        return "\n".join(chunks)

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
                    and invocation.workflow_version == FULLTEXT_WORKFLOW_VERSION
                ):
                    return invocation
        return None


def _metadata_labels(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _metadata_source_ids(value: object) -> list[str]:
    return [
        item for item in _metadata_labels(value) if item.startswith("src_")
    ]


def _shared_labels(groups: list[list[str]]) -> list[str]:
    if not groups:
        return []
    shared = {item.casefold(): item for item in groups[0]}
    for group in groups[1:]:
        present = {item.casefold() for item in group}
        shared = {key: value for key, value in shared.items() if key in present}
    return sorted(shared.values(), key=str.casefold)
