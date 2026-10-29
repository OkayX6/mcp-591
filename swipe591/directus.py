"""Directus client for the swipe app.

Like the back-office gateway's DirectusClient, the methods are the allow-list:
only the `apt_*` collections, only the operations the app needs. The token
belongs to a role limited to those collections (see schema.py), never admin.
"""

import httpx

from swipe591.store import VERDICTS

SEARCHES = "apt_searches"
LISTINGS = "apt_listings"

# Everything the deck and the detail view show, without the raw 591 payload.
LISTING_FIELDS = ",".join([
    "post_id", "search", "title", "price", "price_unit", "area", "layout", "kind", "floor",
    "address", "tags", "photos", "url", "lat", "lng", "detail", "first_seen", "delisted",
    "verdict", "decided_at", "note", "synced_591",
])


class DirectusError(Exception):
    pass


class DirectusStore:
    def __init__(self, base_url: str, token: str, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
            transport=transport,
        )

    def _request(self, method: str, path: str, **kwargs) -> dict | list | None:
        resp = self._http.request(method, path, **kwargs)
        if resp.status_code == 204:
            return None
        if resp.is_error:
            raise DirectusError(
                f"Directus {method} {path} answered {resp.status_code}: {resp.text}"
            )
        return resp.json().get("data")

    # -- searches ------------------------------------------------------------

    def list_searches(self, active_only: bool = False) -> list[dict]:
        params = {"sort": "id", "limit": -1}
        if active_only:
            params["filter[active][_eq]"] = "true"
        return self._request("GET", f"/items/{SEARCHES}", params=params)

    def create_search(self, search: dict) -> dict:
        return self._request("POST", f"/items/{SEARCHES}", json=search)

    def update_search(self, search_id: int, changes: dict) -> dict:
        return self._request("PATCH", f"/items/{SEARCHES}/{search_id}", json=changes)

    def delete_search(self, search_id: int) -> None:
        self._request("DELETE", f"/items/{SEARCHES}/{search_id}")

    # -- listings ------------------------------------------------------------

    def known_post_ids(self, post_ids: list[int]) -> set[int]:
        if not post_ids:
            return set()
        rows = self._request(
            "GET",
            f"/items/{LISTINGS}",
            params={
                "filter[post_id][_in]": ",".join(str(p) for p in post_ids),
                "fields": "post_id",
                "limit": -1,
            },
        )
        return {row["post_id"] for row in rows}

    def add_listing(self, listing: dict) -> None:
        self._request("POST", f"/items/{LISTINGS}", json=listing)

    def get_listing(self, post_id: int) -> dict | None:
        resp = self._http.get(f"/items/{LISTINGS}/{post_id}", params={"fields": LISTING_FIELDS})
        # Directus answers 403, not 404, for an id it doesn't have.
        if resp.status_code in (403, 404):
            return None
        if resp.is_error:
            raise DirectusError(f"Directus GET listing {post_id} answered {resp.status_code}")
        return resp.json()["data"]

    def deck(self, limit: int) -> list[dict]:
        return self._request(
            "GET",
            f"/items/{LISTINGS}",
            params={
                "filter[verdict][_null]": "true",
                "filter[delisted][_eq]": "false",
                "sort": "-first_seen",
                "limit": limit,
                "fields": LISTING_FIELDS,
            },
        )

    def listings_with_verdict(self, verdicts: tuple[str, ...]) -> list[dict]:
        unknown = set(verdicts) - set(VERDICTS)
        if unknown:
            raise ValueError(f"unknown verdicts {unknown}")
        return self._request(
            "GET",
            f"/items/{LISTINGS}",
            params={
                "filter[verdict][_in]": ",".join(verdicts),
                "sort": "-decided_at",
                "limit": -1,
                "fields": LISTING_FIELDS,
            },
        )

    def set_verdict(self, post_id: int, changes: dict) -> dict | None:
        resp = self._http.patch(
            f"/items/{LISTINGS}/{post_id}", json=changes, params={"fields": LISTING_FIELDS}
        )
        if resp.status_code in (403, 404):
            return None
        if resp.is_error:
            raise DirectusError(f"Directus PATCH listing {post_id} answered {resp.status_code}")
        return resp.json()["data"]
