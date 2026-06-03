"""Tests for the file scanner (region detection)."""

# pylint: disable=missing-class-docstring,missing-function-docstring

from netlistio.ingestor.scanner import Scanner
from netlistio.ingestor.spice import SpiceScanStrategy
from netlistio.models.parsing import RegionType


def _scan(path):
    return list(Scanner(path, SpiceScanStrategy()).scan())


class TestSpiceScanStrategy:
    def test_matches_subckt_start(self):
        strategy = SpiceScanStrategy()
        line = b".SUBCKT inv in out vdd vss\n"
        result = strategy.matches_macro_start(line)
        assert result is not None
        _, name = result
        assert name == "inv"

    def test_matches_subckt_case_insensitive(self):
        strategy = SpiceScanStrategy()
        assert strategy.matches_macro_start(b".subckt foo a b\n") is not None
        assert strategy.matches_macro_start(b".Subckt bar x y\n") is not None

    def test_no_match_for_instance(self):
        strategy = SpiceScanStrategy()
        assert strategy.matches_macro_start(b"X1 a b c inv\n") is None

    def test_matches_ends(self):
        strategy = SpiceScanStrategy()
        assert strategy.matches_macro_end(b".ends\n") is True
        assert strategy.matches_macro_end(b".ENDS inv\n") is True
        assert strategy.matches_macro_end(b"R1 a b 1k\n") is False


class TestScanner:
    def test_single_subckt_produces_macro_and_global_regions(self, fixture_path):
        regions = _scan(fixture_path("minimal.sp"))
        types = [r.region_type for r in regions]
        assert RegionType.MACRO in types
        assert RegionType.GLOBAL in types

    def test_library_only_has_multiple_macro_regions(self, fixture_path):
        regions = _scan(fixture_path("library_only.sp"))
        macro_regions = [r for r in regions if r.region_type == RegionType.MACRO]
        assert len(macro_regions) == 2

    def test_hierarchy_file_has_two_macros(self, fixture_path):
        regions = _scan(fixture_path("hierarchy.sp"))
        macro_regions = [r for r in regions if r.region_type == RegionType.MACRO]
        assert len(macro_regions) == 2

    def test_regions_are_contiguous(self, fixture_path):
        regions = _scan(fixture_path("minimal.sp"))
        sorted_regions = sorted(regions, key=lambda r: r.start_byte)
        for i in range(len(sorted_regions) - 1):
            assert sorted_regions[i].end_byte == sorted_regions[i + 1].start_byte

    def test_macro_region_stores_name(self, fixture_path):
        regions = _scan(fixture_path("minimal.sp"))
        macro = next(r for r in regions if r.region_type == RegionType.MACRO)
        assert macro.context_name == "voltage_divider"

    def test_empty_file_produces_no_regions(self, tmp_spice):
        path = tmp_spice("")
        regions = _scan(path)
        assert not regions

    def test_no_subckt_file_produces_single_global_region(self, tmp_spice):
        path = tmp_spice("* just a comment\nR1 a b 1k\n")
        regions = _scan(path)
        assert len(regions) == 1
        assert regions[0].region_type == RegionType.GLOBAL

    def test_nested_subckt_increments_depth(self, tmp_spice):
        # Nested .SUBCKT inside .SUBCKT — hits the depth += 1 branch
        path = tmp_spice(".subckt outer a b\n.subckt inner x y\nR1 x y 1k\n.ends inner\n.ends outer\n")
        regions = _scan(path)
        macro_regions = [r for r in regions if r.region_type == RegionType.MACRO]
        # Outer macro absorbs the inner as content; only one MACRO region at the outer level
        assert len(macro_regions) == 1

    def test_unterminated_subckt_finalized_at_eof(self, tmp_spice):
        path = tmp_spice(".subckt unterminated a b\nR1 a b 1k\n")
        regions = _scan(path)
        # Scanner finalizes on EOF; unterminated MACRO gets emitted
        assert len(regions) >= 1

    def test_scanner_iter_delegates_to_scan(self, fixture_path):
        path = fixture_path("minimal.sp")
        # Each Scanner call owns fresh context state; iter() delegates to scan()
        regions_iter = list(Scanner(path, SpiceScanStrategy()))
        regions_scan = list(Scanner(path, SpiceScanStrategy()).scan())
        assert len(regions_iter) == len(regions_scan)
