import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from mcp_591.rent import map_rent_detail
from swipe591.directus import DirectusError
from swipe591.poller import listing_record, parse_price, poll_once, price_range
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


class RefusingStore(MemoryStore):
    """Like Directus answering 500 to the records it can't store."""

    def __init__(self, refuse):
        super().__init__()
        self._refuse = refuse

    def add_listing(self, listing: dict) -> None:
        if self._refuse(listing):
            raise DirectusError("Directus POST /items/apt_listings answered 500")
        super().add_listing(listing)


def test_one_refused_listing_does_not_stop_the_others():
    store = RefusingStore(refuse=lambda listing: listing["post_id"] == FIRST_ID)
    store.create_search(ZHONGLI_3_ROOMS)
    added = poll_once(store, Fake591(), clock=lambda: NOW)
    assert added == len(SEARCH_PAGE["data"]["items"]) - 1


def test_refused_listing_stays_unknown_for_the_next_poll():
    store = RefusingStore(refuse=lambda listing: listing["post_id"] == FIRST_ID)
    store.create_search(ZHONGLI_3_ROOMS)
    poll_once(store, Fake591(), clock=lambda: NOW)
    assert store.get_listing(FIRST_ID) is None


def test_listing_refused_with_its_detail_is_stored_as_a_bare_card():
    store = RefusingStore(refuse=lambda listing: "detail" in listing)
    store.create_search(ZHONGLI_3_ROOMS)
    poll_once(store, Fake591(), clock=lambda: NOW)
    assert store.get_listing(FIRST_ID)["title"] == SEARCH_PAGE["data"]["items"][0]["title"]


def test_null_bytes_are_removed_from_the_remark():
    detail = map_rent_detail(DETAIL, FIRST_ID)
    detail["remark"] = "近捷運\x00，可養寵物\n押二付一"
    record = listing_record(SEARCH_PAGE["data"]["items"][0], detail, search_id=1, seen_at=NOW)
    assert record["detail"]["remark"] == "近捷運，可養寵物\n押二付一"


def test_title_longer_than_a_directus_string_is_cut_to_255():
    item = {**SEARCH_PAGE["data"]["items"][0], "title": "青埔捷運高鐵" * 70}
    record = listing_record(item, {}, search_id=1, seen_at=NOW)
    assert len(record["title"]) == 255


def test_rent_with_thousands_separator():
    assert parse_price("32,000") == 32000


def test_rent_range_keeps_its_low_end():
    assert parse_price("25,000~35,000") == 25000


def test_rent_without_a_number_is_unknown():
    assert parse_price("面議") is None
