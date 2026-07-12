# Atlas Backend-Only Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [x]`) syntax for tracking.

**Goal:** Convert Atlas into a backend-only personal control plane foundation.

**Architecture:** Keep the existing FastAPI backend behavior, remove frontend serving, rename the
Python package to `atlas`, and introduce SQLAlchemy/Alembic dependencies for upcoming durable
agent/message/task/event modules. The first implementation slice preserves current APIs while
making frontend assets absent by design.

**Tech Stack:** Python 3.11+, uv, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, SQLite, pytest,
pytest-asyncio, ruff.

---

### Task 1: Backend-Only Package Rename

**Files:**
- Modify: `pyproject.toml`
- Move: `src/atlas_console/` to `src/atlas/`
- Modify: `tests/*.py`
- Delete: `client/`

- [x] **Step 1: Write failing tests for backend-only package expectations**

Add tests that import `atlas.main:create_app`, verify `/api/health`, and verify unknown frontend
paths return API-style 404 responses instead of an SPA fallback.

- [x] **Step 2: Run focused tests to verify failure**

Run: `uv run pytest -q tests/test_backend_only.py`

Expected: imports fail while the package is still named `atlas_console`.

- [x] **Step 3: Rename the package and remove frontend serving**

Move `src/atlas_console` to `src/atlas`, update imports and package metadata, remove
`mount_client`, and delete the `client/` tree.

- [x] **Step 4: Run tests to verify the package rename passes**

Run: `uv run pytest -q tests/test_backend_only.py`

Expected: all tests pass.

### Task 2: Preserve Existing Backend Behavior

**Files:**
- Modify: `tests/*.py`
- Modify: `src/atlas/*.py`

- [x] **Step 1: Run the existing suite**

Run: `uv run pytest -q`

Expected: failures only from stale imports or renamed metadata.

- [x] **Step 2: Update imports and compatibility names**

Update tests and source imports from `atlas_console` to `atlas`. Keep current auth, system,
network, probes, sub2api, and todo APIs passing for now.

- [x] **Step 3: Run the suite**

Run: `uv run pytest -q`

Expected: all backend tests pass.

### Task 3: Introduce Control-Plane Structure

**Files:**
- Create: `src/atlas/db/`
- Create: `src/atlas/agents/`
- Create: `src/atlas/messages/`
- Create: `src/atlas/tasks/`
- Create: `src/atlas/events/`

- [x] **Step 1: Add minimal failing import tests for planned modules**

Create tests that import placeholder module boundaries without testing behavior yet.

- [x] **Step 2: Run tests to verify failure**

Run: `uv run pytest -q tests/test_project_structure.py`

Expected: module imports fail.

- [x] **Step 3: Add empty package modules**

Add `__init__.py` files and minimal module placeholders for each planned domain.

- [x] **Step 4: Run tests to verify pass**

Run: `uv run pytest -q tests/test_project_structure.py`

Expected: all tests pass.

### Task 4: Agent Registry MVP

**Files:**
- Modify: `src/atlas/config.py`
- Create: `src/atlas/db/base.py`
- Create: `src/atlas/db/session.py`
- Create: `src/atlas/agents/models.py`
- Create: `src/atlas/agents/repository.py`
- Create: `src/atlas/agents/service.py`
- Modify: `src/atlas/security.py`
- Modify: `src/atlas/main.py`
- Test: `tests/test_agents_api.py`
- Test: `tests/test_agents_service.py`

- [x] **Step 1: Write failing API tests**

Add tests for agent registration, heartbeat, dashboard listing, and rejection when the bearer
token is missing or wrong.

- [x] **Step 2: Run API tests to verify failure**

Run: `uv run pytest -q tests/test_agents_api.py`

Expected: requests fail because `/api/agents/*` routes do not exist yet.

- [x] **Step 3: Write failing service tests**

Add service tests proving registration upserts an agent, heartbeat refreshes `last_seen_at`, and
agents are reported offline after the configured heartbeat grace period.

- [x] **Step 4: Run service tests to verify failure**

Run: `uv run pytest -q tests/test_agents_service.py`

Expected: imports fail because the agent service/repository modules are not implemented yet.

- [x] **Step 5: Implement minimal database, agent repository, service, token auth, and routes**

Use SQLAlchemy with SQLite. Store agent rows durably, authenticate agent endpoints with
`Authorization: Bearer <token>`, and keep dashboard listing under existing cookie auth.

- [x] **Step 6: Run focused tests**

Run: `uv run pytest -q tests/test_agents_service.py tests/test_agents_api.py`

Expected: all agent tests pass.

- [x] **Step 7: Run full verification**

Run: `uv run pytest -q` and `uv run ruff check .`

Expected: all backend tests and lint checks pass.

### Task 5: Direct Messages MVP

**Files:**
- Create: `src/atlas/messages/models.py`
- Create: `src/atlas/messages/repository.py`
- Create: `src/atlas/messages/service.py`
- Modify: `src/atlas/main.py`
- Test: `tests/test_messages_api.py`
- Test: `tests/test_messages_service.py`

- [x] **Step 1: Write failing API tests**

Add tests for bearer-token protected message sending, target-agent inbox polling, message claim,
message acknowledgement, and dashboard-authenticated message lookup.

- [x] **Step 2: Run API tests to verify failure**

Run: `uv run pytest -q tests/test_messages_api.py`

Expected: imports or requests fail because `/api/messages` routes do not exist yet.

- [x] **Step 3: Write failing service tests**

Add tests proving messages are persisted with timestamps, inbox polling only returns pending
messages for the target agent, only the target can claim, and acknowledgement requires a claimed
message.

- [x] **Step 4: Run service tests to verify failure**

Run: `uv run pytest -q tests/test_messages_service.py`

Expected: imports fail because the message service/repository modules are not implemented yet.

- [x] **Step 5: Implement minimal message repository, service, and routes**

Use the existing SQLAlchemy SQLite infrastructure. Keep message statuses small:
`pending`, `claimed`, and `acknowledged`. Store optional `result` and metadata JSON, but do not
implement broadcast, replies, long-polling, WebSocket, or per-agent tokens in this task.

- [x] **Step 6: Run focused tests**

Run: `uv run pytest -q tests/test_messages_service.py tests/test_messages_api.py`

Expected: all message tests pass.

- [x] **Step 7: Run full verification**

Run: `uv run pytest -q` and `uv run ruff check .`

Expected: all backend tests and lint checks pass.
