import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from swipe591.poller import poll_once, price_range
from swipe591.store import MemoryStore

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH_PAGE = json.loads((FIXTURES / "search_rent.json").read_text())
DETAIL = json.loads((FIXTURES / "rent_detail.json").read_text())
FIRST_ID = SEARCH_PAGE["data"]["items"][0]["id"]
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)

ZHONGLI_3_ROOMS = {
    "name": "Zhongli 3 rooms",
    "active": True,
    "region": "桃園市",
    "section": "中壢區",
    "pattern": "3房",
    "price_min": 20000,
    "price_max": 35000,
}


class Fake591:
    """Answers one page of the fixture, then an empty page."""

    def __init__(self, delisted: set[int] = frozenset()):
        self.searches: list[dict] = []
        self.details: list[int] = []
        self._delisted = delisted

    def search_rent(self, **query) -> dict:
        self.searches.append(query)
        if query["first_row"] == 0:
            return copy.deepcopy(SEARCH_PAGE)
        return {"data": {"items": [], "total": SEARCH_PAGE["data"]["total"]}}

    def get_rent_detail(self, post_id) -> dict:
        self.details.append(post_id)
        if post_id in self._delisted:
            return {"status": 1, "data": ""}
        return copy.deepcopy(DETAIL)


def store_with(search: dict) -> MemoryStore:
    store = MemoryStore()
    store.create_search(search)
    return store


def test_stores_every_listing_of_the_page():
    store = store_with(ZHONGLI_3_ROOMS)
    added = poll_once(store, Fake591(), clock=lambda: NOW)
    assert added == len(SEARCH_PAGE["data"]["items"])


def test_new_listing_lands_in_the_deck_with_its_detail():
    store = store_with(ZHONGLI_3_ROOMS)
    poll_once(store, Fake591(), clock=lambda: NOW)
    listing = store.get_listing(FIRST_ID)
    assert listing["price"] == 32000
    assert listing["lat"] is not None
    assert listing["detail"]["deposit"] == DETAIL["data"]["deposit"]
    assert listing["verdict"] is None
    assert listing["delisted"] is False


def test_criteria_reach_591_as_ids():
    store = store_with(ZHONGLI_3_ROOMS)
    source = Fake591()
    poll_once(store, source, clock=lambda: NOW)
    assert source.searches[0]["section_ids"] == [67]
    assert source.searches[0]["price_str"] == "20000_35000"


def test_reads_the_next_page_from_the_number_of_items_received():
    store = store_with(ZHONGLI_3_ROOMS)
    source = Fake591()
    poll_once(store, source, pages=3, clock=lambda: NOW)
    assert [q["first_row"] for q in source.searches] == [0, 30]


def test_known_listing_is_neither_fetched_again_nor_overwritten():
    store = store_with(ZHONGLI_3_ROOMS)
    poll_once(store, Fake591(), clock=lambda: NOW)
    store.set_verdict(FIRST_ID, {"verdict": "like", "decided_at": NOW.isoformat()})
    second = Fake591()
    added = poll_once(store, second, clock=lambda: NOW)
    assert added == 0
    assert second.details == []
    assert store.get_listing(FIRST_ID)["verdict"] == "like"


def test_listing_gone_before_its_detail_is_stored_as_delisted():
    store = store_with(ZHONGLI_3_ROOMS)
    poll_once(store, Fake591(delisted={FIRST_ID}), clock=lambda: NOW)
    assert store.get_listing(FIRST_ID)["delisted"] is True


def test_paused_search_is_not_polled():
    store = store_with({**ZHONGLI_3_ROOMS, "active": False})
    source = Fake591()
    poll_once(store, source, clock=lambda: NOW)
    assert source.searches == []


def test_search_with_a_stale_district_is_skipped_not_fatal():
    store = store_with({**ZHONGLI_3_ROOMS, "section": "大安區"})
    store.create_search({**ZHONGLI_3_ROOMS, "name": "Zhongli again"})
    added = poll_once(store, Fake591(), clock=lambda: NOW)
    assert added == len(SEARCH_PAGE["data"]["items"])


def test_open_ended_price_range_gets_a_high_ceiling():
    assert price_range({"price_min": 20000, "price_max": None}) == "20000_9999999"


def test_no_price_bounds_means_no_price_filter():
    assert price_range({"price_min": None, "price_max": None}) is None
