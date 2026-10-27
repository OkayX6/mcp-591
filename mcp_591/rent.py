"""Rental search logic shared by the MCP server and the swipe591 web app.

Pure functions only: turning human-readable criteria into Client591 arguments,
and 591's raw rent payloads into flat dicts. No network access here.
"""

from mcp_591.constants import (
    PATTERNS,
    REGIONS,
    RENT_KINDS,
    SECTIONS,
    SECTIONS_BY_REGION,
    SHAPES,
)

RENT_LISTING_KEYS = {
    "post_id", "title", "price", "price_unit", "area_name",
    "layoutStr", "kind_name", "address", "tags", "refresh_time",
}


def resolve(mapping: dict, name: str | None, label: str) -> int | None:
    if name is None:
        return None
    match = next((k for k, v in mapping.items() if v == name), None)
    if match is None:
        raise ValueError(f"無效的{label}：{name!r}，可用：{list(mapping.values())}")
    return match


def build_rent_query(
    region: str,
    section: str | None = None,
    kind: str | None = None,
    shape: str | None = None,
    pattern: str | None = None,
    price_str: str | None = None,
    keywords: str | None = None,
) -> dict:
    """Keyword arguments for Client591.search_rent (without first_row)."""
    region_id = resolve(REGIONS, region, "縣市")
    if region_id is None:
        raise ValueError("縣市不可為空")

    if section:
        section_ids = [
            sid for sid, (sname, rid) in SECTIONS.items()
            if sname == section and rid == region_id
        ]
        if not section_ids:
            available = list(SECTIONS_BY_REGION[region_id].values())
            raise ValueError(f"找不到區域 {section!r}，可用：{available}")
    else:
        section_ids = list(SECTIONS_BY_REGION[region_id].keys())

    return {
        "region_id": region_id,
        "section_ids": section_ids,
        "kind": resolve(RENT_KINDS, kind, "物件類型") if kind else None,
        "shape_ids": [resolve(SHAPES, shape, "建物型態")] if shape else None,
        "pattern_ids": [resolve(PATTERNS, pattern, "格局")] if pattern else None,
        "price_str": price_str,
        "keywords": keywords,
    }


def filter_rent_listing(item: dict) -> dict:
    result = {k: v for k, v in item.items() if k in RENT_LISTING_KEYS}
    result["post_id"] = item.get("id")
    return result


def map_rent_search(result: dict) -> dict:
    data = result.get("data", {})
    # 591 rent API returns `total` as a string; coerce to int so callers get the
    # same type as search_sale.
    total = data.get("total")
    return {
        "total_rows": int(total) if total is not None else None,
        "next_first_row": data.get("firstRow"),
        "listings": [filter_rent_listing(item) for item in data.get("items", [])],
    }


def map_rent_detail(resp: dict, post_id: str | int) -> dict:
    d = resp.get("data")
    if not isinstance(d, dict) or not d:
        raise ValueError(f"Listing {post_id} not found (may be delisted)")

    info = {item["key"]: item["value"] for item in d.get("info", [])}
    house_info = {item["key"]: item["value"] for item in d.get("houseInfo", {}).get("data", [])}
    addr = d.get("address", {})
    link = d.get("linkInfo", {})
    gtm = d.get("gtm_detail_data", {})
    remark_block = d.get("remark", {})

    return {
        "title": d.get("title"),
        "price": d.get("price"),
        "price_unit": d.get("priceUnit"),
        "deposit": d.get("deposit"),
        "kind": gtm.get("kind_name"),
        "area": info.get("area"),
        "floor": info.get("floor"),
        "shape": info.get("shape"),
        "layout": info.get("layout"),
        "region": gtm.get("region_name"),
        "section": gtm.get("section_name"),
        "address": addr.get("data"),
        "lat": addr.get("lat"),
        "lng": addr.get("lng"),
        "traffic": addr.get("traffic"),
        "lease": house_info.get("leaseTime"),
        "move_in": house_info.get("comeDate"),
        "pet": house_info.get("pet"),
        "cook": house_info.get("cook"),
        "sex": house_info.get("sex"),
        "facilities": gtm.get("facility_name"),
        "tags": d.get("tags"),
        "agent": link.get("name"),
        "agent_role": link.get("roleName"),
        "phone": link.get("mobile"),
        "remark": remark_block.get("content", ""),
    }
