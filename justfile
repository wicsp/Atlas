set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

test-server:
    cd apps/server && uv run pytest -q && uv run ruff check .

test-console:
    cd apps/console && npm run lint && npm test

test: test-server test-console

build-console:
    cd apps/console && npm run build

status:
    git status --short
