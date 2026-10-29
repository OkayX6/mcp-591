import pytest

from mcp_591.rent import build_rent_query


class TestBuildRentQuery:
    def test_resolves_region_and_section_names_to_591_ids(self):
        query = build_rent_query("桃園市", section="中壢區")
        assert query["region_id"] == 6
        assert query["section_ids"] == [67]

    def test_whole_county_when_no_section(self):
        query = build_rent_query("台北市")
        assert len(query["section_ids"]) == 12

    def test_resolves_kind_shape_and_pattern(self):
        query = build_rent_query("桃園市", kind="整層住家", shape="電梯大樓", pattern="3房")
        assert query["kind"] == 1
        assert query["shape_ids"] == [2]
        assert query["pattern_ids"] == [3]

    def test_unknown_section_lists_the_valid_ones(self):
        with pytest.raises(ValueError, match="中壢區"):
            build_rent_query("桃園市", section="大安區")

    def test_unknown_region_is_refused(self):
        with pytest.raises(ValueError, match="縣市"):
            build_rent_query("Paris")
