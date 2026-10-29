"""What the app and the poller need from storage.

`DirectusStore` (directus.py) is the real one; `MemoryStore` is the in-memory
fake the tests use. Records are plain dicts carrying the Directus field names
(see schema.py).
"""

from typing import Protocol

LIKED = ("like", "superlike")
DISLIKED = ("dislike",)
VERDICTS = LIKED + DISLIKED


class Store(Protocol):
    def list_searches(self, active_only: bool = False) -> list[dict]: ...
    def create_search(self, search: dict) -> dict: ...
    def update_search(self, search_id: int, changes: dict) -> dict: ...
    def delete_search(self, search_id: int) -> None: ...

    def known_post_ids(self, post_ids: list[int]) -> set[int]: ...
    def add_listing(self, listing: dict) -> None: ...
    def get_listing(self, post_id: int) -> dict | None: ...
    def deck(self, limit: int) -> list[dict]: ...
    def listings_with_verdict(self, verdicts: tuple[str, ...]) -> list[dict]: ...
    def set_verdict(self, post_id: int, changes: dict) -> dict | None: ...


class MemoryStore:
    def __init__(self) -> None:
        self.searches: dict[int, dict] = {}
        self.listings: dict[int, dict] = {}
        self._next_search_id = 1

    def list_searches(self, active_only: bool = False) -> list[dict]:
        return [dict(s) for s in self.searches.values() if s.get("active") or not active_only]

    def create_search(self, search: dict) -> dict:
        created = {**search, "id": self._next_search_id}
        self.searches[self._next_search_id] = created
        self._next_search_id += 1
        return dict(created)

    def update_search(self, search_id: int, changes: dict) -> dict:
        self.searches[search_id].update(changes)
        return dict(self.searches[search_id])

    def delete_search(self, search_id: int) -> None:
        self.searches.pop(search_id, None)

    def known_post_ids(self, post_ids: list[int]) -> set[int]:
        return {p for p in post_ids if p in self.listings}

    def add_listing(self, listing: dict) -> None:
        self.listings[listing["post_id"]] = dict(listing)

    def get_listing(self, post_id: int) -> dict | None:
        found = self.listings.get(post_id)
        return dict(found) if found else None

    def deck(self, limit: int) -> list[dict]:
        waiting = [
            item for item in self.listings.values()
            if item.get("verdict") is None and not item.get("delisted")
        ]
        waiting.sort(key=lambda item: item["first_seen"], reverse=True)
        return [dict(item) for item in waiting[:limit]]

    def listings_with_verdict(self, verdicts: tuple[str, ...]) -> list[dict]:
        judged = [item for item in self.listings.values() if item.get("verdict") in verdicts]
        judged.sort(key=lambda item: item["decided_at"], reverse=True)
        return [dict(item) for item in judged]

    def set_verdict(self, post_id: int, changes: dict) -> dict | None:
        if post_id not in self.listings:
            return None
        self.listings[post_id].update(changes)
        return dict(self.listings[post_id])
