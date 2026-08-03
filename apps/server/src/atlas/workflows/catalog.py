import hashlib

from atlas.work.models import ExecutionRequirements, WorkflowRef

from .models import WorkflowDefinitionCreate, WorkflowStepDefinition

BUILTIN_WORKFLOWS = [
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "bilibili.favorites-scan",
            "version": "1",
            "project_id": "bilibili-ingest",
            "description": (
                "Read the Atlas Bilibili favorites folder on macsp, remove each "
                "accepted item, and return bounded inputs for summary fan-out."
            ),
            "steps": [
                {
                    "name": "scan",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["bilibili-cookie:read"],
                    },
                    "max_attempts": 3,
                    "priority": 30,
                }
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "bilibili.summary",
            "version": "5",
            "project_id": "bilibili-capture",
            "description": (
                "Acquire a Bilibili transcript on the data-local Mac, then summarize it "
                "through a replaceable agent executor."
            ),
            "steps": [
                {
                    "name": "acquire",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["bilibili-cookie:read"],
                    },
                    "max_attempts": 1,
                    "priority": 5,
                },
                {
                    "name": "summarize",
                    "depends_on": ["acquire"],
                    "requirements": {"executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 5,
                },
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "paper.ingest",
            "version": "1",
            "project_id": "paper-library",
            "description": (
                "Import one paper into the local Zotero library, extract abstract "
                "(or PDF leading text if abstract is unavailable), and publish a "
                "paper-preview-v1 summary resource."
            ),
            "steps": [
                {
                    "name": "ingest",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["zotero-library:write", "zotero-library:read"],
                    },
                    "max_attempts": 3,
                    "priority": 20,
                },
                {
                    "name": "summarize",
                    "depends_on": ["ingest"],
                    "requirements": {"executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 20,
                },
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "paper.fulltext",
            "version": "2",
            "project_id": "paper-library",
            "description": (
                "Read Zotero-indexed PDF text for an ingested paper (importing to "
                "Zotero first when the paper arrived via a fallback path), and publish "
                "a layered paper-reading-brief-v2 Resource with bounded arXiv figure context."
            ),
            "steps": [
                {
                    "name": "zotero_import",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["zotero-library:write"],
                    },
                    "max_attempts": 3,
                    "priority": 25,
                },
                {
                    "name": "extract",
                    "depends_on": ["zotero_import"],
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["zotero-library:read"],
                    },
                    "max_attempts": 3,
                    "priority": 25,
                },
                {
                    "name": "summarize",
                    "depends_on": ["extract"],
                    "requirements": {"executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 25,
                },
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "paper.fulltext",
            "version": "3",
            "project_id": "paper-library",
            "description": (
                "Read Zotero-indexed PDF text, cache bounded key figures in Atlas with an "
                "arXiv source fallback, and publish paper-reading-brief-v3."
            ),
            "steps": [
                {
                    "name": "zotero_import",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["zotero-library:write"],
                    },
                    "max_attempts": 3,
                    "priority": 25,
                },
                {
                    "name": "extract",
                    "depends_on": ["zotero_import"],
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["zotero-library:read"],
                    },
                    "max_attempts": 3,
                    "priority": 25,
                },
                {
                    "name": "summarize",
                    "depends_on": ["extract"],
                    "requirements": {"executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 25,
                },
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "web.summary",
            "version": "1",
            "project_id": "web-capture",
            "description": "Summarize a verified local web extraction with a replaceable agent.",
            "steps": [
                {
                    "name": "summarize",
                    "requirements": {"node_ids": ["macsp"], "executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 5,
                }
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "vortex.comparison",
            "version": "1",
            "project_id": "resource-review",
            "description": "Compare a Source summary with explicit human comments.",
            "steps": [
                {
                    "name": "compare",
                    "requirements": {"node_ids": ["macsp"], "executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 20,
                }
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "paper.organize",
            "version": "1",
            "project_id": "paper-library",
            "description": (
                "Suggest paper tags and categories using the existing Atlas vocabulary. "
                "The result remains a machine proposal until a person confirms it."
            ),
            "steps": [
                {
                    "name": "suggest",
                    "requirements": {"node_ids": ["macsp"], "executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 15,
                }
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "knowledge.suggest",
            "version": "1",
            "project_id": "knowledge-base",
            "description": (
                "Propose new knowledge pages or improvements from explicit Atlas material. "
                "The result remains a machine suggestion until a person applies it."
            ),
            "steps": [
                {
                    "name": "suggest",
                    "requirements": {"node_ids": ["macsp"], "executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 15,
                }
            ],
        }
    ),
]


def builtin_step_contract(
    name: str, version: str, step_name: str
) -> tuple[WorkflowRef, WorkflowStepDefinition, ExecutionRequirements]:
    definition = next(
        item for item in BUILTIN_WORKFLOWS if item.name == name and item.version == version
    )
    step = next(item for item in definition.steps if item.name == step_name)
    digest = hashlib.sha256(definition.model_dump_json().encode()).hexdigest()
    return (
        WorkflowRef(name=name, version=version, digest=f"sha256:{digest}"),
        step,
        step.requirements,
    )
