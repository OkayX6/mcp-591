"""The `apt_*` data model in Directus, applied by `python -m swipe591.apply_schema`.

This file is the source of truth: change the model here, then re-run the
script with an admin token. Applying is additive and idempotent: missing
collections, fields and relations are created; nothing is altered or dropped
(a rename or a type change is a manual step in the Directus UI).
"""


def _field(name: str, type_: str, *, interface: str | None = None, **schema) -> dict:
    field = {"field": name, "type": type_, "meta": {}, "schema": schema}
    if interface:
        field["meta"]["interface"] = interface
    return field


COLLECTIONS = [
    {
        "collection": "apt_searches",
        "meta": {"icon": "manage_search", "note": "591 swipe: saved rent searches"},
        "fields": [
            {"field": "id", "type": "integer", "meta": {"hidden": True},
             "schema": {"is_primary_key": True, "has_auto_increment": True}},
            _field("name", "string", is_nullable=False),
            _field("active", "boolean", default_value=True),
            _field("region", "string", is_nullable=False),
            _field("section", "string"),
            _field("kind", "string"),
            _field("shape", "string"),
            _field("pattern", "string"),
            _field("price_min", "integer"),
            _field("price_max", "integer"),
            _field("keywords", "string"),
        ],
    },
    {
        "collection": "apt_listings",
        "meta": {"icon": "apartment", "note": "591 swipe: listings found, and what Denis thought"},
        "fields": [
            # 591's own post id is the key: dedup is a primary-key lookup.
            {"field": "post_id", "type": "integer", "meta": {},
             "schema": {"is_primary_key": True, "has_auto_increment": False}},
            _field("search", "integer"),
            _field("title", "string"),
            _field("price", "integer"),
            _field("price_unit", "string"),
            _field("area", "string"),
            _field("layout", "string"),
            _field("kind", "string"),
            _field("floor", "string"),
            _field("address", "string"),
            _field("tags", "json"),
            _field("photos", "json"),
            _field("url", "string"),
            _field("lat", "float"),
            _field("lng", "float"),
            _field("detail", "json"),
            _field("first_seen", "timestamp"),
            _field("delisted", "boolean", default_value=False),
            # like / superlike / dislike; null = still in the deck.
            _field("verdict", "string"),
            _field("decided_at", "timestamp"),
            _field("note", "text"),
            # Phase 2: whether the like was pushed to the 591 account's favorites.
            _field("synced_591", "boolean", default_value=False),
        ],
    },
]

RELATIONS = [
    {
        "collection": "apt_listings",
        "field": "search",
        "related_collection": "apt_searches",
        "schema": {"on_delete": "SET NULL"},
    },
]

# What the app's role may do, per collection.
PERMISSIONS = {
    "apt_searches": ("create", "read", "update", "delete"),
    "apt_listings": ("create", "read", "update"),
}
