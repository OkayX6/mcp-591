"""Fills the deck: for each active saved search, read the first pages of 591's
rent results and store every listing not seen before, with its detail.

Run as `python -m swipe591.poller` (loops forever) or `--once`.
"""

import argparse
import logging
import random
import time
from datetime import UTC, datetime
from typing import Callable, Protocol

from mcp_591.client import Client591
from mcp_591.rent import build_rent_query, filter_rent_listing, map_rent_detail
from swipe591.store import Store

log = logging.getLogger("swipe591.poller")


class RentSource(Protocol):
    def search_rent(self, **query) -> dict: ...
    def get_rent_detail(self, post_id: str | int) -> dict: ...


def price_range(search: dict) -> str | None:
    low, high = search.get("price_min"), search.get("price_max")
    if low is None and high is None:
        return None
    return f"{low or 0}_{high or 9_999_999}"


def query_for(search: dict) -> dict:
    return build_rent_query(
        search["region"],
        section=search.get("section") or None,
        kind=search.get("kind") or None,
        shape=search.get("shape") or None,
        pattern=search.get("pattern") or None,
        price_str=price_range(search),
        keywords=search.get("keywords") or None,
    )


def parse_price(text) -> int | None:
    digits = "".join(c for c in str(text or "") if c.isdigit())
    return int(digits) if digits else None


def listing_record(item: dict, detail: dict | None, search_id: int, seen_at: datetime) -> dict:
    summary = filter_rent_listing(item)
    detail = detail or {}
    return {
        "post_id": summary["post_id"],
        "search": search_id,
        "title": summary.get("title"),
        "price": parse_price(summary.get("price")),
        "price_unit": summary.get("price_unit"),
        "area": summary.get("area_name"),
        "layout": detail.get("layout") or summary.get("layoutStr"),
        "kind": summary.get("kind_name"),
        "floor": item.get("floor_name"),
        "address": detail.get("address") or summary.get("address"),
        "tags": [t.strip() for t in summary.get("tags") or []],
        "photos": item.get("photoList") or [],
        "url": item.get("url") or f"https://rent.591.com.tw/{summary['post_id']}",
        "lat": _float(detail.get("lat")),
        "lng": _float(detail.get("lng")),
        "detail": detail or None,
        "first_seen": seen_at.isoformat(),
        "delisted": detail == {},
        "verdict": None,
    }


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def poll_once(
    store: Store,
    source: RentSource,
    *,
    pages: int = 3,
    pause: Callable[[], None] = lambda: None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Stores the new listings of every active search; returns how many."""
    added = 0
    for search in store.list_searches(active_only=True):
        try:
            query = query_for(search)
        except ValueError as e:
            log.warning("search %s (%s) skipped: %s", search["id"], search.get("name"), e)
            continue

        items: list[dict] = []
        first_row = 0
        for _ in range(pages):
            data = source.search_rent(**query, first_row=first_row).get("data", {})
            page = data.get("items", [])
            items.extend(page)
            pause()
            # The response's `firstRow` echoes the offset asked for, not the next
            # one (the fixture asked for 0 and says 0), so advance by hand.
            first_row += len(page)
            if not page or first_row >= int(data.get("total") or 0):
                break

        by_id = {item["id"]: item for item in items if item.get("id")}
        known = store.known_post_ids(list(by_id))
        for post_id, item in by_id.items():
            if post_id in known:
                continue
            try:
                detail = map_rent_detail(source.get_rent_detail(post_id), post_id)
            except ValueError:
                detail = {}  # delisted between the list and the detail call
            pause()
            store.add_listing(listing_record(item, detail, search["id"], clock()))
            added += 1
        log.info("search %s (%s): %d listings read, %d new",
                 search["id"], search.get("name"), len(by_id), len(by_id) - len(known))
    return added


def _polite_pause() -> None:
    time.sleep(random.uniform(2.0, 5.0))


def main() -> None:
    from swipe591.config import Settings
    from swipe591.directus import DirectusStore

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = Settings.from_env()
    store = DirectusStore(settings.directus_url, settings.directus_token)
    while True:
        try:
            added = poll_once(store, Client591(), pages=settings.poll_pages, pause=_polite_pause)
            log.info("poll done: %d new listings", added)
        except Exception:
            log.exception("poll failed")
        if args.once:
            return
        jitter = random.uniform(-0.15, 0.15) * settings.poll_minutes * 60
        time.sleep(settings.poll_minutes * 60 + jitter)


if __name__ == "__main__":
    main()
