# Atlas Console

Atlas Console is the private, mobile-friendly Resource review workbench defined by Atlas RFC 0004.
It is deliberately narrower than a general control-plane dashboard.

## Boundaries

- Atlas owns Source, Resource, review, Run, and KnowledgeRef metadata.
- Lumio performs Mac-local Vortex mutations through capability-routed Runs.
- The Console uses only the Atlas operator session cookie and never receives a control or agent
  credential.
- It does not render Mac-local `file://` artifacts or write human Knowledge prose.

## Development

Node.js 22.13 or newer is required.

```bash
npm install
ATLAS_API_ORIGIN=http://100.100.10.3:8000 npm run dev
npm run lint
npm test
```

The Vite development server proxies same-origin `/api/*` requests to `ATLAS_API_ORIGIN`. Production
uses a Tailscale-only reverse proxy: `/api/*` targets Atlas and all other paths target this app.

## AMAX deployment

The checked-in units assume `/home/wicsp/projects/AtlasConsole`:

```bash
npm ci
npm run build
systemctl --user enable --now atlas-console.service atlas-console-proxy.service
```

- Vinext listens only on `127.0.0.1:8788`.
- Caddy listens only on the AMAX Tailscale address at `http://100.100.10.3:8787`.
- Caddy proxies `/api/*` to Atlas at `127.0.0.1:8000`, so the browser keeps one origin and an
  HttpOnly Atlas session cookie.
- Neither unit contains an Atlas credential.

## User workflow

1. Sign in with the existing Atlas operator password.
2. Find Source groups under `待判断`; all summary versions remain visible inside each group.
3. Open the original or the generated Obsidian card.
4. Choose `写评论` to enqueue the fixed `vortex-comment-v1` Run. An online Mac Lumio creates the
   empty note, registers the KnowledgeRef, marks the Resource reviewed, and refreshes its card.
5. Choose `忽略` for irrelevant unreferenced Resources, or `恢复` to return one to pending.

The chronological `时间上最新` badge is not a recommendation and does not select a preferred
summary.
