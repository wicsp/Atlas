# System Boundaries

This document turns the repository charter into concrete placement and dependency rules.

## Dependency direction

```text
nix-config ──provisions──▶ Atlas service
     │
     └──────provisions──▶ Lumio / pi runtime

Lumio ─────public API───▶ Atlas
Atlas ─────work/events──▶ protocol-compatible agents
```

Provisioning is not a runtime library dependency. Atlas must run without Lumio, and Lumio should
remain useful when Atlas is temporarily unavailable.

## Responsibility matrix

| Concern | Atlas | Lumio | nix-config |
| --- | --- | --- | --- |
| Project and work status | Own | Read/report through API | No |
| Agent registry and heartbeat | Own | Participate | Provision credentials/config |
| Job scheduling and run history | Own | Claim and execute | Provision workers |
| pi extensions and TUI | No | Own | Install/link |
| Bilibili, paper, and browser workflow | Track status only | Own | Provide tools |
| API schema | Own | Consume | Configure endpoint |
| Database migrations | Own | No | Invoke during deployment if required |
| launchd/systemd units | Describe runtime requirements | No | Own |
| Secret values | No | No | No; reference secret store only |
| Large files | Artifact references only | Produce/consume | Provision storage paths |
| Human-authored knowledge | Link/index only | May open an empty capture UI | Provision applications/paths |

## Control plane and data plane

Atlas is the control plane. The data plane remains distributed:

| Data | Authority or storage |
| --- | --- |
| Source code and Markdown history | Git repositories |
| Bibliography, PDFs, PDF annotations | Zotero and its configured sync |
| Human knowledge comments | Obsidian-compatible Markdown vault |
| Video, transcript, and generated resource files | File or object storage |
| Checkpoints and large experiment outputs | AMAX or object storage |
| Embedding and search indexes | Rebuildable AMAX-local storage |

Atlas records stable IDs, content hashes, provenance, lifecycle state, and locations. It should not
copy every payload into SQLite merely to make it visible in the console.

## Core object vocabulary

These objects are deliberately distinct:

- **Project**: a bounded context for ongoing work.
- **WorkItem**: something actionable that needs progress, review, or a decision.
- **Job**: a schedulable request to perform work.
- **Run**: one concrete execution attempt for a job.
- **Event**: an append-only fact that already happened.
- **ArtifactRef**: metadata and a location for an external output.
- **Source**: external original material such as a paper, video, webpage, dataset, or code revision.
- **Resource**: derived assistance such as a transcript, AI summary, extraction, or comparison.
- **KnowledgeComment**: a human-authored observation with source anchors and revision relations.
- **Node**: a device or host.
- **Agent**: a process capable of interacting with Atlas.

Only actionable things are WorkItems. A PDF, heartbeat, comment, GPU reading, or summary is not
made into a WorkItem merely to reuse a UI component.

## Content layers inside a WorkItem

The useful part of the "Everything is a Task" pattern is retained for actionable work:

- **Specification**: the current goal, constraints, and acceptance criteria.
- **Activity log**: append-only state and execution events produced by Atlas.
- **Discussion**: human/agent conversation about the work.
- **Runs**: concrete execution attempts.
- **Artifacts**: outputs attached by reference.

Use `Discussion`, not `Comments`, in the control plane. `Comment` is reserved for a human-authored
knowledge record so that operational conversation cannot be mistaken for personal knowledge.

## Knowledge boundary

AI and automated workers may:

- create and update Resource records;
- extract source anchors and propose links;
- create an empty human-comment template with source metadata;
- search existing human comments without rewriting them;
- report that an old comment has a later revision.

They may not:

- silently write prose into a human KnowledgeComment;
- label AI-authored content as `authored_by: human`;
- overwrite an older human position to hide its history;
- turn vector similarity into a confirmed semantic relationship.

Confirmed knowledge relations use explicit types such as `supports`, `contradicts`, `revises`,
`extends`, `questions`, and `inspired_by`. AI can propose; a human confirms.

## Configuration boundary

`nix-config` may provide:

- endpoint URLs;
- executable and data paths;
- service users and service declarations;
- names of secret files or credentials supplied by a secret manager;
- restart policy and resource limits.

It must not contain:

- Atlas database rows or live queue state;
- application migrations implemented as Nix business logic;
- copied Lumio skill implementations;
- passwords, bearer tokens, API keys, or session secrets in the repository.

## Compatibility and observability

Connected components should report, when available:

```yaml
software_version: 0.1.0
git_revision: abc1234
protocol_version: atlas-agent-v1
config_generation: optional-host-generation
capabilities:
  - resource.bilibili.transcript
```

Atlas should eventually display those fields together with online status. Protocol changes must be
backward compatible within a declared version or introduce a new version explicitly.

## Repository guidance

Each repository's README and `AGENTS.md` should link back to this boundary document. Repeated
cross-boundary mistakes belong in the nearest repository's `AGENTS.md`; enforceable rules should
also be covered by tests, schema validation, or deployment checks.

