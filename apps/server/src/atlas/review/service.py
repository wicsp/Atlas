from __future__ import annotations

import hashlib

from atlas.content.models import CommentCreate
from atlas.content.service import ContentService
from atlas.work.models import ProjectCreate, RunCreate
from atlas.work.service import WorkService
from atlas.workflows.catalog import builtin_step_contract

from .models import (
    CommentCompleteResponse,
    ComparisonRequestResponse,
)

REVIEW_PROJECT_ID = "resource-review"
COMPARISON_JOB_NAME = "vortex-comparison-v1"


class UnsupportedReviewResourceError(ValueError):
    """Raised when an operator action is not valid for this Resource kind."""


class ReviewService:
    def __init__(self, content: ContentService, work: WorkService) -> None:
        self._content = content
        self._work = work

    def complete_comment(
        self,
        resource_id: str,
        body_markdown: str,
        supplied_content_hash: str | None = None,
    ) -> CommentCompleteResponse:
        resource = self._content.get_resource(resource_id)
        if resource.kind != "summary":
            raise UnsupportedReviewResourceError(
                "Human comments currently require a summary Resource"
            )

        note_id = f"Atlas/Comments/{resource_id}"
        note_uri = f"/#resource-{resource_id}"
        content_hash = f"sha256:{hashlib.sha256(body_markdown.encode()).hexdigest()}"
        if supplied_content_hash is not None and supplied_content_hash != content_hash:
            raise ValueError("Comment content_hash does not match body_markdown")
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
        workflow, step, requirements = builtin_step_contract(
            "vortex.comparison", "1", "compare"
        )
        bundle = self._resource_bundle(resource_id)
        comments = self._content.list_comments(source_id=resource.source_id, limit=500)
        run = self._work.enqueue_run(
            RunCreate(
                project_id=REVIEW_PROJECT_ID,
                job_name=COMPARISON_JOB_NAME,
                input={
                    "resource_id": resource_id,
                    "bundle": bundle,
                    "comments": [comment.model_dump(mode="json") for comment in comments],
                },
                priority=step.priority,
                max_attempts=step.max_attempts,
                metadata={"requested_via": "atlas-console"},
                workflow=workflow,
                step_name=step.name,
                requirements=requirements,
            )
        )
        return ComparisonRequestResponse(run=run, reused=False)

    def _resource_bundle(self, resource_id: str) -> dict:
        resource = self._content.get_resource(resource_id)
        source = self._content.get_source(resource.source_id)
        artifact = next(
            (
                item
                for item in self._work.list_artifacts(resource.produced_by_run_id)
                if item.artifact_id == resource.artifact_id
            ),
            None,
        )
        if artifact is None:
            raise ValueError(f"Resource {resource_id} has no Artifact")
        try:
            content = self._work.get_artifact_content(artifact.artifact_id).content
        except KeyError:
            content = None
        artifact_data = artifact.model_dump(mode="json")
        if content is not None:
            artifact_data["content"] = content
        return {
            "resource": resource.model_dump(mode="json"),
            "source": source.model_dump(mode="json"),
            "artifact": artifact_data,
        }
