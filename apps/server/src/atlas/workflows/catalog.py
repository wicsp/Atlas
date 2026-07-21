from .models import WorkflowDefinitionCreate


BUILTIN_WORKFLOWS = [
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
    )
]
