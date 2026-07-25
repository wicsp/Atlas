# RFC 0010: Runtime-neutral workflow execution

- **Status:** Implemented
- **Decision date:** 2026-07-21
- **Owners:** Atlas execution protocol and node-side runner implementations
- **Protocol:** `atlas-runner-v1`

## Summary

Atlas is the data, policy, workflow, and scheduling control plane. Pi, Codex, scripts, and future
runtimes are replaceable executors. Lumio is a Pi distribution and may provide an adapter, but it
is not part of the Atlas scheduling authority.

The stable execution hierarchy is:

```text
WorkflowDefinition -> WorkflowInvocation -> Step/Run -> Attempt
                                                   -> Node Runner -> Executor
                                                                  -> Agent session or process
```

A Node describes placement facts. A Runner is a node-local execution plane. An Executor describes
how that Runner can start work, such as `pi`, `codex`, `python`, or a constrained process adapter.
A Workflow contains business behavior and may reference versioned skills and prompt templates.
Business workflow names are not permanent properties of a Runner.

## Boundaries

Atlas owns:

- immutable Workflow references and structured invocation inputs;
- deterministic step state, placement, leases, attempts, cancellation, and result acceptance;
- Node, Runner, Executor, grant, ArtifactRef, and Resource contracts;
- authorization policy and auditable state transitions.

A Runner owns:

- validating an assigned execution specification;
- enforcing the grants issued to one Attempt;
- starting, monitoring, cancelling, and cleaning up executors;
- publishing bounded structured results and ArtifactRefs.

An Executor owns runtime-specific behavior. Agent executors construct sessions and load skills;
script executors start allowlisted programs. Neither kind defines Atlas domain state.

Lumio owns Pi interaction, extensions, prompts, themes, browser capture UI, and local UX. It does
not poll for or execute Atlas work. AtlasRunner is the only node-local execution plane, including
the loopback ingress that turns a browser capture into a local Artifact and Atlas Workflow
invocation.

## Placement and authorization

Placement facts and business behavior are separate:

- `node_ids` and `node_labels` select data or machine locality;
- `executors` select acceptable execution mechanisms;
- `grants` request protected resources for one Attempt;
- the Workflow reference selects business behavior.

A Runner advertising an available grant does not give every task permission to use it. This first
protocol slice uses the advertised set only for placement. A later runner daemon must validate the
issued grant against a local allowlist before starting an executor.

## Implemented migration

`atlas-runner-v1` provides:

- `/api/runners/register`, `/api/runners/{id}/heartbeat`, and `/api/runners` provide the new identity
  surface;
- Runner records temporarily reuse the existing scoped-credential store;
- Run records add `workflow`, `step_name`, and `requirements` without changing the SQLite schema;
- the existing `capabilities_required` field and `/api/agents` endpoints remain only as protocol
  compatibility surfaces;
- Bilibili, Web summary, Vortex comparison, comment setup/sync, and Resource purge use versioned
  Workflow references and AtlasRunner adapters;
- the Chrome capture extension starts sending when its toolbar popup opens, while AtlasRunner owns
  the credential-free loopback bridge and local extraction Artifact write;
- Lumio registers only an interaction identity, advertises no local grants or legacy handlers, and
  never claims Runs.

New workflow-constrained Runs cannot be claimed by a legacy Agent identity. A matching Runner must
satisfy node, executor, label, and available-grant placement requirements.

## Remaining follow-up

1. Add transferable Artifact storage before scheduling dependent steps across nodes.
2. Replace the temporary Runner bootstrap credential used by `atlas-control:write` with a scoped
   per-Attempt control grant.
3. Remove `atlas-agent-v3` work endpoints after deployed compatibility clients are retired.

The Atlas scheduler remains deterministic code. An operator Agent may propose a workflow, but it
cannot bypass Atlas placement, grant, lease, approval, or state-transition rules.
