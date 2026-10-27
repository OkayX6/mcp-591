"""DirectusStore and apply_schema against a faked Directus (httpx.MockTransport)."""

import json

import httpx

from swipe591.apply_schema import apply
from swipe591.directus import DirectusStore


class FakeDirectus:
    def __init__(self, routes: dict[tuple[str, str], object]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.routes.get((request.method, request.url.path), {"data": None})
        if isinstance(answer, int):
            return httpx.Response(answer, json={"errors": []})
        return httpx.Response(200, json=answer)

    def bodies(self, method: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.method == method]


def store_on(fake: FakeDirectus) -> DirectusStore:
    transport = httpx.MockTransport(fake)
    return DirectusStore("https://directus.example", "app-token", transport=transport)


class TestDirectusStore:
    def test_sends_the_app_token(self):
        fake = FakeDirectus({("GET", "/items/apt_searches"): {"data": []}})
        store_on(fake).list_searches()
        assert fake.requests[0].headers["authorization"] == "Bearer app-token"

    def test_deck_asks_for_unjudged_listings_still_online_newest_first(self):
        fake = FakeDirectus({("GET", "/items/apt_listings"): {"data": []}})
        store_on(fake).deck(20)
        params = fake.requests[0].url.params
        assert params["filter[verdict][_null]"] == "true"
        assert params["filter[delisted][_eq]"] == "false"
        assert params["sort"] == "-first_seen"

    def test_known_post_ids_come_back_as_a_set(self):
        fake = FakeDirectus({("GET", "/items/apt_listings"): {"data": [{"post_id": 21103645}]}})
        known = store_on(fake).known_post_ids([21103645, 21099871])
        assert known == {21103645}

    def test_known_post_ids_of_nothing_asks_nothing(self):
        fake = FakeDirectus({})
        store_on(fake).known_post_ids([])
        assert fake.requests == []

    def test_listing_directus_does_not_have_is_none(self):
        # Directus answers 403 rather than 404 for a missing item.
        fake = FakeDirectus({("GET", "/items/apt_listings/1"): 403})
        assert store_on(fake).get_listing(1) is None

    def test_verdict_is_a_patch_of_the_listing(self):
        updated = {"data": {"post_id": 21103645}}
        fake = FakeDirectus({("PATCH", "/items/apt_listings/21103645"): updated})
        store_on(fake).set_verdict(21103645, {"verdict": "like"})
        assert fake.bodies("PATCH") == [{"verdict": "like"}]


def schema_client(fake: FakeDirectus) -> httpx.Client:
    return httpx.Client(base_url="https://directus.example", transport=httpx.MockTransport(fake))


class TestApplySchema:
    def test_empty_directus_gets_both_collections_and_the_relation(self):
        fake = FakeDirectus({
            ("GET", "/collections"): {"data": [{"collection": "wine_bottles"}]},
            ("GET", "/relations"): {"data": []},
        })
        done = apply(schema_client(fake))
        assert done == ["create collection apt_searches", "create collection apt_listings",
                        "add relation apt_listings.search"]

    def test_existing_collection_only_gets_its_missing_fields(self):
        from swipe591.schema import COLLECTIONS

        searches_fields = [{"field": f["field"]} for f in COLLECTIONS[0]["fields"]]
        listings_fields = [{"field": f["field"]} for f in COLLECTIONS[1]["fields"]
                           if f["field"] != "note"]
        fake = FakeDirectus({
            ("GET", "/collections"): {"data": [{"collection": "apt_searches"},
                                               {"collection": "apt_listings"}]},
            ("GET", "/fields/apt_searches"): {"data": searches_fields},
            ("GET", "/fields/apt_listings"): {"data": listings_fields},
            ("GET", "/relations"): {"data": [{"collection": "apt_listings", "field": "search"}]},
        })
        assert apply(schema_client(fake)) == ["add field apt_listings.note"]

    def test_dry_run_writes_nothing(self):
        fake = FakeDirectus({
            ("GET", "/collections"): {"data": []},
            ("GET", "/relations"): {"data": []},
        })
        apply(schema_client(fake), dry_run=True)
        assert fake.bodies("POST") == []

    def test_policy_gets_only_the_missing_permissions(self):
        fake = FakeDirectus({
            ("GET", "/collections"): {"data": [{"collection": "apt_searches"},
                                               {"collection": "apt_listings"}]},
            ("GET", "/fields/apt_searches"): {"data": []},
            ("GET", "/fields/apt_listings"): {"data": []},
            ("GET", "/relations"): {"data": [{"collection": "apt_listings", "field": "search"}]},
            ("GET", "/permissions"): {"data": [
                {"collection": c, "action": a}
                for c, a in [("apt_searches", "create"), ("apt_searches", "read"),
                             ("apt_searches", "update"), ("apt_searches", "delete"),
                             ("apt_listings", "read"), ("apt_listings", "update")]
            ]},
        })
        done = apply(schema_client(fake), policy="policy-uuid", dry_run=True)
        assert [d for d in done if d.startswith("grant")] == ["grant create on apt_listings"]
