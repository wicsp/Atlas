#!/usr/bin/env python3
"""Enqueue one paper.fulltext@3 reading brief per existing paper Source."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _request(base_url: str, path: str, token: str, payload: dict[str, str] | None = None) -> Any:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method="POST" if payload is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _targets(resources: list[dict[str, Any]]) -> list[tuple[str, str]]:
    sources_with_v3 = {
        resource["source_id"]
        for resource in resources
        if resource.get("metadata", {}).get("profile_id") == "paper-reading-brief-v3"
    }
    previews: dict[str, dict[str, Any]] = {}
    for resource in resources:
        if resource.get("metadata", {}).get("profile_id") != "paper-preview-v1":
            continue
        source_id = resource["source_id"]
        current = previews.get(source_id)
        if current is None or resource["created_at"] > current["created_at"]:
            previews[source_id] = resource
    return sorted(
        (source_id, resource["resource_id"])
        for source_id, resource in previews.items()
        if source_id not in sources_with_v3
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("ATLAS_AGENT_SHARED_TOKEN", "").strip()
    if not token:
        print("ATLAS_AGENT_SHARED_TOKEN is required", file=sys.stderr)
        return 2
    try:
        resources = _request(
            args.base_url,
            "/api/resources?kind=summary&limit=500",
            token,
        )
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
        print(f"failed to list Resources: {error}", file=sys.stderr)
        return 1
    if not isinstance(resources, list):
        print("Atlas returned a non-list Resource response", file=sys.stderr)
        return 1

    targets = _targets(resources)
    print(f"paper reading brief backfill targets: {len(targets)}")
    if args.dry_run:
        return 0

    accepted = 0
    reused = 0
    failed = 0
    for source_id, preview_resource_id in targets:
        try:
            response = _request(
                args.base_url,
                "/api/paper/fulltext",
                token,
                {
                    "source_id": source_id,
                    "preview_resource_id": preview_resource_id,
                },
            )
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
            failed += 1
            print(f"failed {source_id}: {error}")
            continue
        if response.get("reused"):
            reused += 1
        else:
            accepted += 1
        print(f"queued {source_id}: {'reused' if response.get('reused') else 'new'}")
    print(f"backfill complete: new={accepted} reused={reused} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
