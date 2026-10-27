from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from swipe591.app import COOKIE, create_app
from swipe591.directus import DirectusError
from swipe591.store import MemoryStore

PASSWORD = "qingpu-2026"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC).timestamp()


def a_listing(**overrides) -> dict:
    listing = {
        "post_id": 21103645,
        "search": 1,
        "title": "青埔捷運高鐵國家大院3房含車管",
        "price": 32000,
        "layout": "3房1廳",
        "area": "19坪",
        "photos": [],
        "first_seen": "2026-10-27T08:00:00+00:00",
        "delisted": False,
        "verdict": None,
        "decided_at": None,
    }
    return {**listing, **overrides}


QINGPU = a_listing()
ZHONGLI_STATION = a_listing(post_id=21099871, title="中壢火車站電梯2房",
                            first_seen="2026-10-27T07:00:00+00:00")
GONE = a_listing(post_id=20877102, title="已下架", delisted=True)


@pytest.fixture
def store() -> MemoryStore:
    store = MemoryStore()
    for listing in (QINGPU, ZHONGLI_STATION, GONE):
        store.add_listing(listing)
    return store


def client_for(store: MemoryStore) -> TestClient:
    app = create_app(store, password=PASSWORD, session_secret="test-secret",
                     cookie_secure=False, clock=lambda: NOW)
    return TestClient(app)


@pytest.fixture
def signed_in(store) -> TestClient:
    client = client_for(store)
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
    return client


def verdict_url(listing: dict) -> str:
    return f"/api/listings/{listing['post_id']}/verdict"


def deck_ids(client: TestClient) -> list[int]:
    return [item["post_id"] for item in client.get("/api/deck").json()]


class TestLogin:
    def test_api_refuses_without_session(self, store):
        assert client_for(store).get("/api/deck").status_code == 401

    def test_wrong_password_is_refused(self, store):
        resp = client_for(store).post("/api/login", json={"password": "guess"})
        assert resp.status_code == 401

    def test_wrong_password_sets_no_cookie(self, store):
        client = client_for(store)
        client.post("/api/login", json={"password": "guess"})
        assert COOKIE not in client.cookies

    def test_forged_cookie_is_refused(self, store):
        client = client_for(store)
        client.cookies.set(COOKIE, "99999999999.deadbeef")
        assert client.get("/api/deck").status_code == 401

    def test_sixth_attempt_in_a_minute_is_throttled_even_with_the_right_password(self, store):
        client = client_for(store)
        for _ in range(5):
            client.post("/api/login", json={"password": "guess"})
        resp = client.post("/api/login", json={"password": PASSWORD})
        assert resp.status_code == 429

    def test_page_itself_loads_without_session(self, store):
        assert client_for(store).get("/").status_code == 200


class TestDeck:
    def test_newest_first(self, signed_in):
        assert deck_ids(signed_in) == [QINGPU["post_id"], ZHONGLI_STATION["post_id"]]

    def test_delisted_listing_is_not_dealt(self, signed_in):
        assert GONE["post_id"] not in deck_ids(signed_in)

    def test_liked_listing_leaves_the_deck(self, signed_in):
        signed_in.put(verdict_url(QINGPU), json={"verdict": "like"})
        assert deck_ids(signed_in) == [ZHONGLI_STATION["post_id"]]

    def test_liked_listing_shows_in_likes(self, signed_in):
        signed_in.put(verdict_url(QINGPU), json={"verdict": "like"})
        liked = signed_in.get("/api/listings", params={"verdict": "liked"}).json()
        assert [item["post_id"] for item in liked] == [QINGPU["post_id"]]

    def test_superlike_counts_as_liked(self, signed_in):
        signed_in.put(verdict_url(QINGPU), json={"verdict": "superlike"})
        liked = signed_in.get("/api/listings", params={"verdict": "liked"}).json()
        assert [item["post_id"] for item in liked] == [QINGPU["post_id"]]

    def test_dislike_is_not_a_like(self, signed_in):
        signed_in.put(verdict_url(QINGPU), json={"verdict": "dislike"})
        liked = signed_in.get("/api/listings", params={"verdict": "liked"}).json()
        assert liked == []

    def test_verdict_is_timestamped(self, signed_in):
        resp = signed_in.put(verdict_url(QINGPU), json={"verdict": "like"})
        assert resp.json()["decided_at"] == "2026-10-27T09:00:00+00:00"

    def test_undo_puts_it_back_in_the_deck(self, signed_in):
        path = verdict_url(QINGPU)
        signed_in.put(path, json={"verdict": "dislike"})
        signed_in.put(path, json={"verdict": None})
        assert QINGPU["post_id"] in deck_ids(signed_in)

    def test_unknown_verdict_is_refused(self, signed_in):
        resp = signed_in.put(verdict_url(QINGPU), json={"verdict": "maybe"})
        assert resp.status_code == 422

    def test_verdict_on_unknown_listing_is_404(self, signed_in):
        resp = signed_in.put("/api/listings/1/verdict", json={"verdict": "like"})
        assert resp.status_code == 404


class TestSearches:
    ZHONGLI = {"name": "Zhongli 3 rooms", "region": "桃園市", "section": "中壢區", "pattern": "3房",
               "price_min": 20000, "price_max": 35000}

    def test_created_search_is_listed(self, signed_in):
        signed_in.post("/api/searches", json=self.ZHONGLI)
        names = [s["name"] for s in signed_in.get("/api/searches").json()]
        assert names == ["Zhongli 3 rooms"]

    def test_district_of_another_city_is_refused(self, signed_in):
        resp = signed_in.post("/api/searches", json={**self.ZHONGLI, "section": "大安區"})
        assert resp.status_code == 400

    def test_inverted_price_range_is_refused(self, signed_in):
        resp = signed_in.post("/api/searches", json={**self.ZHONGLI, "price_min": 40000})
        assert resp.status_code == 400

    def test_pausing_a_search_keeps_it(self, signed_in):
        created = signed_in.post("/api/searches", json=self.ZHONGLI).json()
        signed_in.put(f"/api/searches/{created['id']}", json={**self.ZHONGLI, "active": False})
        assert signed_in.get("/api/searches").json()[0]["active"] is False


class DirectusDown(MemoryStore):
    def deck(self, limit: int) -> list[dict]:
        raise DirectusError("Directus GET /items/apt_listings answered 503: maintenance")


def test_directus_failure_is_a_502_naming_it():
    client = client_for(DirectusDown())
    client.post("/api/login", json={"password": PASSWORD})
    resp = client.get("/api/deck")
    assert resp.status_code == 502
    assert "Directus" in resp.json()["detail"]
