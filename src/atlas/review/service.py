from __future__ import annotations

from urllib.parse import quote

from atlas.content.models import CommentCreate
from atlas.content.service import ContentService
from atlas.work.models import ProjectCreate, RunCreate
from atlas.work.service import WorkService

from .models import (
    CommentCompleteResponse,
    CommentRequestResponse,
    CommentSyncRequestResponse,
    ComparisonRequestResponse,
)

REVIEW_PROJECT_ID = "resource-review"
COMMENT_JOB_NAME = "vortex-comment-v1"
COMMENT_RUN_PRIORITY = 100
COMPARISON_JOB_NAME = "vortex-comparison-v1"
COMPARISON_RUN_PRIORITY = 20
COMMENT_SYNC_JOB_NAME = "vortex-comment-sync-v1"
COMMENT_SYNC_RUN_PRIORITY = 100


class ResourceAlreadyCommentedError(ValueError):
    """Raised when a Resource already has a human KnowledgeRef."""


class UnsupportedReviewResourceError(ValueError):
    """Raised when an operator action is not valid for this Resource kind."""


class ReviewService:
    def __init__(self, content: ContentService, work: WorkService) -> None:
        self._content = content
        self._work = work

    def request_comment(self, resource_id: str) -> CommentRequestResponse:
        resource = self._content.get_resource(resource_id)
        if resource.kind != "summary":
            raise UnsupportedReviewResourceError(
                "Human comment requests currently require a summary Resource"
            )

        knowledge_ref = self._content.find_knowledge_ref_for_resource(resource_id)
        if knowledge_ref is not None:
            raise ResourceAlreadyCommentedError(
                f"Resource {resource_id} already has KnowledgeRef "
                f"{knowledge_ref.knowledge_ref_id}"
            )

        for run in self._work.list_runs(project_id=REVIEW_PROJECT_ID, limit=500):
            if (
                run.job_name == COMMENT_JOB_NAME
                and run.status in {"pending", "claimed"}
                and run.input.get("resource_id") == resource_id
            ):
                return CommentRequestResponse(run=run, reused=True)

        self._work.create_project(
            ProjectCreate(
                project_id=REVIEW_PROJECT_ID,
                name="Resource Review",
                description="Operator-requested, Mac-local Resource review actions.",
            )
        )
        run = self._work.enqueue_run(
            RunCreate(
                project_id=REVIEW_PROJECT_ID,
                job_name=COMMENT_JOB_NAME,
                capabilities_required=[COMMENT_JOB_NAME],
                input={"resource_id": resource_id},
                priority=COMMENT_RUN_PRIORITY,
                max_attempts=3,
                metadata={"requested_via": "atlas-console"},
            )
        )
        return CommentRequestResponse(run=run, reused=False)

    def request_comment_sync(self, resource_id: str) -> CommentSyncRequestResponse:
        resource = self._content.get_resource(resource_id)
        if resource.kind != "summary":
            raise UnsupportedReviewResourceError(
                "Human comment sync currently requires a summary Resource"
            )
        for run in self._work.list_runs(project_id=REVIEW_PROJECT_ID, limit=500):
            if (
                run.job_name == COMMENT_SYNC_JOB_NAME
                and run.status in {"pending", "claimed"}
                and run.input.get("resource_id") == resource_id
            ):
                return CommentSyncRequestResponse(run=run, reused=True)
        self._work.create_project(
            ProjectCreate(
                project_id=REVIEW_PROJECT_ID,
                name="Resource Review",
                description="Operator-requested, Mac-local Resource review actions.",
            )
        )
        run = self._work.enqueue_run(
            RunCreate(
                project_id=REVIEW_PROJECT_ID,
                job_name=COMMENT_SYNC_JOB_NAME,
                capabilities_required=[COMMENT_SYNC_JOB_NAME],
                input={"resource_id": resource_id},
                priority=COMMENT_SYNC_RUN_PRIORITY,
                max_attempts=3,
                metadata={"requested_via": "atlas-console"},
            )
        )
        return CommentSyncRequestResponse(run=run, reused=False)

    def complete_comment(
        self,
        resource_id: str,
        body_markdown: str,
        content_hash: str,
    ) -> CommentCompleteResponse:
        resource = self._content.get_resource(resource_id)
        if resource.kind != "summary":
            raise UnsupportedReviewResourceError(
                "Human comments currently require a summary Resource"
            )

        note_id = f"Knowledge/Comments/{resource_id}"
        note_uri = (
            "obsidian://open?vault=Vortex&file="
            f"{quote(note_id, safe='')}"
        )
        reviewed, knowledge_ref, comment = self._content.complete_comment(
            CommentCreate(
                resource_id=resource_id,
                body_markdown=body_markdown,
                content_hash=content_hash,
            ),
            note_id,
            note_uri,
        )
        return CommentCompleteResponse(
            resource=reviewed,
            knowledge_ref=knowledge_ref,
            comment=comment,
        )

    def request_comparison(self, resource_id: str) -> ComparisonRequestResponse:
        resource = self._content.get_resource(resource_id)
        if resource.kind != "summary":
            raise UnsupportedReviewResourceError(
                "Friction comparison currently requires a summary Resource"
            )
        for run in self._work.list_runs(project_id=REVIEW_PROJECT_ID, limit=500):
            if (
                run.job_name == COMPARISON_JOB_NAME
                and run.status in {"pending", "claimed"}
                and run.input.get("resource_id") == resource_id
            ):
                return ComparisonRequestResponse(run=run, reused=True)
        self._work.create_project(
            ProjectCreate(
                project_id=REVIEW_PROJECT_ID,
                name="Resource Review",
                description="Operator-requested, Mac-local Resource review actions.",
            )
        )
        run = self._work.enqueue_run(
            RunCreate(
                project_id=REVIEW_PROJECT_ID,
                job_name=COMPARISON_JOB_NAME,
                capabilities_required=[COMPARISON_JOB_NAME],
                input={"resource_id": resource_id},
                priority=COMPARISON_RUN_PRIORITY,
                max_attempts=2,
                metadata={"requested_via": "atlas-console"},
            )
        )
        return ComparisonRequestResponse(run=run, reused=False)
