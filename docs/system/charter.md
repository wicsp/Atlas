# Personal Infrastructure Charter

## Purpose

The Atlas monorepo, Lumio, and `nix-config` are repositories for one personal infrastructure
system. They have different responsibilities and release cycles, but they must evolve through
shared end-to-end capabilities rather than independent feature lists. Atlas keeps its server and
Console together while preserving their runtime boundary.

The shortest description of the system is:

> Lumio executes. Atlas coordinates. `nix-config` provisions.

The surrounding research tools keep their own authority:

> Zotero preserves evidence. Obsidian records human-authored intellectual history.

## Repository missions

### Atlas

Atlas is the personal infrastructure control plane. It owns the durable protocol and state for:

- projects and actionable work;
- nodes, agents, services, jobs, runs, and events;
- capture inbox entries and resource-processing state;
- artifact metadata and locations, but not large artifact bytes;
- system health, notifications, and operator-facing APIs.

Atlas coordinates work. It does not contain agent-specific implementation logic and does not
replace Git, Zotero, object storage, file synchronization, SSH, Tailscale, or service managers.

### Lumio

Lumio is the personal AI execution layer built on pi. It owns:

- pi extensions, skills, prompts, themes, and interaction behavior;
- AI-assisted acquisition and processing workflows;
- adapters for browser, Zotero, Obsidian, and other interactive tools;
- Atlas client behavior used to advertise capabilities, receive work, and report results;
- permission gates and explicit human-confirmation boundaries.

Lumio executes work through public Atlas protocols. It does not own global project state,
scheduling, or Atlas persistence.

### nix-config

`nix-config` is the declarative environment and deployment layer. It owns:

- packages, executable versions, paths, and host-specific configuration;
- installation or linking of Atlas and Lumio components;
- launchd/systemd service declarations;
- non-secret configuration and references to separately managed secrets;
- reproducible checks for the machines it manages.

`nix-config` provisions software. It does not contain application business logic, runtime state,
or secret values.

## System invariants

1. **Dependencies point through protocols.** Lumio uses the Atlas HTTP API; it never reads the
   Atlas database. Atlas never imports or installs Lumio.
2. **One authority per kind of data.** API schemas live in Atlas, execution workflows in Lumio,
   deployment declarations in `nix-config`, bibliography in Zotero, and human knowledge in the
   knowledge vault.
3. **AI output is a resource, not human knowledge.** AI may create summaries, transcripts,
   comparisons, and relationship proposals. It must not silently create or rewrite a person's
   knowledge comments.
4. **Large data stays out of coordination messages.** Atlas stores artifact references, hashes,
   provenance, status, and locations. Files remain in the storage system suited to them.
5. **Every deployment identifies its revision.** Running Atlas and connected agents should expose
   software version, Git revision, and protocol version where possible.
6. **Cross-system changes are vertical slices.** Define the protocol in Atlas, update the server
   and Console atomically when needed, implement the executor in Lumio, provision it in
   `nix-config`, then verify the complete path.
7. **Private networking is not authentication.** Tailscale limits reachability; Atlas still
   authenticates operators and agents.
8. **Derived state is rebuildable.** Summaries, embeddings, indexes, dashboards, and cached views
   may be deleted and reconstructed without damaging sources or human knowledge.

## Decision ownership

| Decision | Owning repository or system |
| --- | --- |
| HTTP API and control-plane data model | Atlas |
| Agent capability implementation | Lumio |
| Host packages and service declarations | `nix-config` |
| Human comment drafts | Knowledge vault |
| Explicitly completed synchronized comments | Atlas |
| Bibliographic metadata, PDFs, and annotations | Zotero |
| Experiment source code | The experiment repository |
| Large experiment artifacts | AMAX storage or an object store |
| Cross-system architecture and RFCs | Atlas `docs/` |

## Change process

A change needs an Atlas RFC when it modifies a cross-repository contract, authentication model,
artifact location scheme, durable control-plane object, or human-knowledge boundary. Internal
refactors that preserve those contracts remain local to their repository.

The normal delivery order is:

1. State the user-visible outcome and acceptance criteria.
2. Define or revise the Atlas protocol.
3. Implement and test the Atlas behavior.
4. Implement and test the Lumio adapter or capability.
5. Add the minimal `nix-config` deployment declaration.
6. Run one end-to-end smoke test.
7. Record the deployed revisions and update the RFC status.

## Non-goals

- A monorepo containing every project and every piece of personal data.
- A universal database that replaces specialized tools.
- A frontend that owns the backend model.
- A general multi-user agent platform or plugin marketplace.
- Automatic conversion of AI summaries into authoritative knowledge.
