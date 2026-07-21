# RFC 0010: Runtime-neutral workflow execution

- **Status:** Accepted for incremental implementation
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

Lumio continues to own Pi interaction, extensions, prompts, themes, and local UX. Its current Atlas
poller is the first compatibility implementation of a Pi executor, not the final scheduler.

## Placement and authorization

Placement facts and business behavior are separate:

- `node_ids` and `node_labels` select data or machine locality;
- `executors` select acceptable execution mechanisms;
- `grants` request protected resources for one Attempt;
- the Workflow reference selects business behavior.

A Runner advertising an available grant does not give every task permission to use it. This first
protocol slice uses the advertised set only for placement. A later runner daemon must validate the
issued grant against a local allowlist before starting an executor.

## Compatibility phase

`atlas-runner-v1` is additive:

- `/api/runners/register`, `/api/runners/{id}/heartbeat`, and `/api/runners` provide the new identity
  surface;
- Runner records temporarily reuse the existing scoped-credential store;
- Run records add `workflow`, `step_name`, and `requirements` without changing the SQLite schema;
- the existing `capabilities_required` field and `/api/agents` endpoints remain for deployed v3
  clients;
- Lumio registers Pi as an Executor while continuing to advertise legacy handler names until
  existing Runs and enqueue paths migrate to versioned Workflow definitions.

New workflow-constrained Runs cannot be claimed by a legacy Agent identity. A matching Runner must
satisfy node, executor, label, and available-grant placement requirements.

## Follow-up slices

1. Define immutable WorkflowDefinition storage and validation.
2. Introduce a standalone Atlas Runner daemon with Pi, Codex, and script adapters.
3. Migrate Bilibili summary into a multi-step Workflow and remove handler-name capabilities.
4. Separate Obsidian projection from summary production.
5. Add transferable Artifact storage before scheduling dependent steps across nodes.
6. Deprecate `atlas-agent-v3` work polling after all deployed nodes use Runner identities.

The Atlas scheduler remains deterministic code. An operator Agent may propose a workflow, but it
cannot bypass Atlas placement, grant, lease, approval, or state-transition rules.
