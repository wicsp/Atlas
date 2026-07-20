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

The checked-in units assume the monorepo is at `/home/wicsp/projects/Atlas` and this application is
at `/home/wicsp/projects/Atlas/apps/console`:

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
2. Find Source groups under `待判断`; the current Resource for each analysis profile is visible,
   while KnowledgeRef-cited history remains available.
3. Open the original or the generated Obsidian card.
4. Choose `写评论` to open the Resource Card and immediately create/open the deterministic local
   `Knowledge/Comments/<resource_id>.md` draft. No server request is made and the Resource remains
   pending.
5. After writing, choose `完成评论` to register the metadata-only KnowledgeRef and mark the
   Resource reviewed. Comment prose never leaves Obsidian.
6. Choose `生成观点对比` to compare the selected summary only with comments for that Resource or
   Source. Lumio renders deterministic Obsidian callout cards for source view, personal view, and
   the candidate judgment; use `查看对比` to open the latest result directly.
7. Choose `忽略` for irrelevant unreferenced Resources, or `恢复` to return one to pending.

The chronological `时间上最新` badge is not a recommendation and does not select a preferred
summary.
