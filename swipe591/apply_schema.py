"""Create the `apt_*` collections in Directus from swipe591/schema.py.

    DIRECTUS_URL=https://... DIRECTUS_ADMIN_TOKEN=... uv run python -m swipe591.apply_schema \
        [--policy <policy uuid>] [--dry-run]

Needs an admin token (Directus only lets admins change the schema): use one for
the run, never store it. Additive and idempotent. With --policy (Directus 11),
also grants that policy the permissions in schema.PERMISSIONS, so the app's
own token can be a role limited to `apt_*`.
"""

import argparse
import os
import sys

import httpx

from swipe591.schema import COLLECTIONS, PERMISSIONS, RELATIONS


def apply(http: httpx.Client, *, policy: str | None = None, dry_run: bool = False) -> list[str]:
    """Returns what was (or, dry run, would be) done."""
    done: list[str] = []

    def call(method: str, path: str, **kwargs) -> dict:
        resp = http.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def write(description: str, method: str, path: str, body: dict) -> None:
        done.append(description)
        if not dry_run:
            call(method, path, json=body)

    existing = {c["collection"] for c in call("GET", "/collections")["data"]}
    for collection in COLLECTIONS:
        name = collection["collection"]
        if name not in existing:
            write(f"create collection {name}", "POST", "/collections",
                  {**collection, "schema": {}})
            continue
        fields = {f["field"] for f in call("GET", f"/fields/{name}")["data"]}
        for field in collection["fields"]:
            if field["field"] not in fields:
                write(f"add field {name}.{field['field']}", "POST", f"/fields/{name}", field)

    relations = {(r["collection"], r["field"]) for r in call("GET", "/relations")["data"]}
    for relation in RELATIONS:
        if (relation["collection"], relation["field"]) not in relations:
            write(f"add relation {relation['collection']}.{relation['field']}",
                  "POST", "/relations", relation)

    if policy:
        granted = {
            (p["collection"], p["action"])
            for p in call("GET", "/permissions",
                          params={"filter[policy][_eq]": policy, "limit": -1})["data"]
        }
        for collection, actions in PERMISSIONS.items():
            for action in actions:
                if (collection, action) not in granted:
                    write(f"grant {action} on {collection}", "POST", "/permissions",
                          {"policy": policy, "collection": collection, "action": action,
                           "fields": ["*"], "permissions": {}, "validation": {}})
    return done


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", help="Directus policy id of the app's role")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = os.environ.get("DIRECTUS_URL")
    token = os.environ.get("DIRECTUS_ADMIN_TOKEN")
    if not url or not token:
        sys.exit("Set DIRECTUS_URL and DIRECTUS_ADMIN_TOKEN")
    with httpx.Client(base_url=url.rstrip("/"), timeout=30.0,
                      headers={"Authorization": f"Bearer {token}"}) as http:
        steps = apply(http, policy=args.policy, dry_run=args.dry_run)
    prefix = "would " if args.dry_run else ""
    print("\n".join(f"{prefix}{step}" for step in steps) or "schema already up to date")


if __name__ == "__main__":
    main()
