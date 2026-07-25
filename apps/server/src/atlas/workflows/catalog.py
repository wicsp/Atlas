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
            "name": "paper.preview",
            "version": "1",
            "project_id": "paper-discovery",
            "description": (
                "Acquire bounded scholarly metadata for one arXiv paper, then create an "
                "explicitly abstract-based preview through a replaceable agent executor."
            ),
            "steps": [
                {
                    "name": "acquire",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                    },
                    "max_attempts": 3,
                    "priority": 10,
                },
                {
                    "name": "summarize",
                    "depends_on": ["acquire"],
                    "requirements": {"executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 10,
                },
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "paper.accept",
            "version": "1",
            "project_id": "paper-library",
            "description": (
                "Accept one abstract-previewed paper into the local Zotero library, "
                "read Zotero-indexed PDF text, and publish a full-text summary."
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
                    "priority": 20,
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
                    "priority": 20,
                },
                {
                    "name": "summarize",
                    "depends_on": ["extract"],
                    "requirements": {"executors": ["pi"]},
                    "max_attempts": 2,
                    "priority": 20,
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
            "name": "vortex.comment",
            "version": "1",
            "project_id": "resource-review",
            "description": "Create or synchronize a human-owned Vortex comment on the local Mac.",
            "steps": [
                {
                    "name": "setup",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["obsidian-vault:write"],
                    },
                    "max_attempts": 3,
                    "priority": 100,
                }
            ],
        }
    ),
    WorkflowDefinitionCreate.model_validate(
        {
            "name": "vortex.comment-sync",
            "version": "1",
            "project_id": "resource-review",
            "description": (
                "Read a completed local Vortex comment and atomically publish it to Atlas."
            ),
            "steps": [
                {
                    "name": "sync",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["obsidian-vault:read", "atlas-control:write"],
                    },
                    "max_attempts": 3,
                    "priority": 100,
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
            "name": "vortex.resource-purge",
            "version": "1",
            "project_id": "resource-review",
            "description": "Delete verified local Artifact bytes and rebuildable Vortex cards.",
            "steps": [
                {
                    "name": "purge",
                    "requirements": {
                        "node_ids": ["macsp"],
                        "executors": ["script"],
                        "grants": ["artifact-store:delete", "obsidian-vault:write"],
                    },
                    "max_attempts": 3,
                    "priority": 10,
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
