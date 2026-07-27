set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

doctor:
    @command -v git
    @command -v uv
    @command -v npm
    @command -v systemctl
    @command -v curl

sync-server:
    cd apps/server && uv sync --frozen

sync-console:
    cd apps/console && npm ci

sync: sync-server sync-console

test-server:
    cd apps/server && uv run --frozen pytest -q && uv run --frozen ruff check .

test-console:
    cd apps/console && npm run lint && npm test

test: test-server test-console

audit-console:
    cd apps/console && npm audit --omit=dev --audit-level=high

ci: test audit-console

build-console:
    cd apps/console && npm run build

build: build-console

install-units:
    mkdir -p "${HOME}/.config/systemd/user"
    cp --remove-destination apps/server/deploy/systemd/user/atlas.service "${HOME}/.config/systemd/user/atlas.service"
    cp --remove-destination apps/console/deploy/atlas-console.service "${HOME}/.config/systemd/user/atlas-console.service"
    cp --remove-destination apps/console/deploy/atlas-console-proxy.service "${HOME}/.config/systemd/user/atlas-console-proxy.service"
    systemctl --user daemon-reload

restart:
    systemctl --user restart atlas.service atlas-console.service atlas-console-proxy.service

health:
    curl --fail --silent --show-error --retry 15 --retry-delay 1 --retry-all-errors http://127.0.0.1:8000/api/health
    curl --insecure --fail --silent --show-error --retry 15 --retry-delay 1 --retry-all-errors --output /dev/null https://100.100.10.3:8787

deploy: ci build install-units restart health

restart-runner:
    launchctl unload ~/Library/LaunchAgents/org.nix-community.home.atlas-runner.plist 2>/dev/null || true
    sleep 1
    launchctl load ~/Library/LaunchAgents/org.nix-community.home.atlas-runner.plist
    @echo "Runner restarted. Check: tail -f ~/.local/state/atlas-runner/runner.log"

push-deploy:
    git push origin main
    ssh 100.100.10.3 "cd /home/wicsp/projects/Atlas && git pull && just build-console && just restart && just health"
    @echo "Atlas deployed to amax."

status:
    git status --short
