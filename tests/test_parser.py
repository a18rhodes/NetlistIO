"""
Direct tests for parser internals — bypasses multiprocessing to reach coverage.

ChunkParser, SpiceChunkParser, SpiceChunkParserFactory, and _worker_entry_point
all execute inside subprocess workers during normal operation, so they are invisible
to pytest-cov. These tests call them directly in the main process.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring

from pathlib import Path

from netlistio.ingestor.common import open_mmap
from netlistio.ingestor.parser import _worker_entry_point
from netlistio.ingestor.scanner import Scanner
from netlistio.ingestor.spice import (
    SpiceChunkParser,
    SpiceChunkParserFactory,
    SpiceLineParser,
    SpiceScanStrategy,
)
from netlistio.models.parsing import ParseRegion, RegionType

FIXTURES = Path(__file__).parent / "fixtures"


def _macro_region(sp_path: Path) -> ParseRegion:
    return next(r for r in Scanner(sp_path, SpiceScanStrategy()).scan() if r.region_type == RegionType.MACRO)


def _last_global_region(sp_path: Path) -> ParseRegion:
    """Returns the last GLOBAL region — the one containing top-level instances after all subckts."""
    regions = [r for r in Scanner(sp_path, SpiceScanStrategy()).scan() if r.region_type == RegionType.GLOBAL]
    return regions[-1]


class TestWorkerEntryPoint:
    def test_parses_macro_region(self):
        path = FIXTURES / "minimal.sp"
        region = _macro_region(path)
        result = _worker_entry_point((str(path), region, SpiceChunkParserFactory()))
        assert len(result.cells) == 1
        assert result.cells[0].name == "voltage_divider"

    def test_parses_global_region(self):
        path = FIXTURES / "hierarchy.sp"
        region = _last_global_region(path)
        result = _worker_entry_point((str(path), region, SpiceChunkParserFactory()))
        # Global region of hierarchy.sp has one top-level instance
        assert any(c.name == "Xbuf_inst" for c in result.cells)


class TestSpiceChunkParserFactory:
    def test_call_returns_spice_chunk_parser(self):
        path = FIXTURES / "minimal.sp"
        region = _macro_region(path)
        with open_mmap(path) as mm:
            parser = SpiceChunkParserFactory()(path, mm, region)
        assert isinstance(parser, SpiceChunkParser)


class TestSpiceChunkParserDirect:
    def _make_parser(self, path: Path, region: ParseRegion):
        with open_mmap(path) as mm:
            lp = SpiceLineParser(str(path), mm, region)
            cp = SpiceChunkParser(mm, region, lp)
            return cp.parse()

    def test_parse_macro_region(self):
        path = FIXTURES / "minimal.sp"
        result = self._make_parser(path, _macro_region(path))
        assert len(result.cells) == 1

    def test_parse_global_region_with_instances(self):
        path = FIXTURES / "hierarchy.sp"
        result = self._make_parser(path, _last_global_region(path))
        assert any(c.name == "Xbuf_inst" for c in result.cells)

    def test_continuation_lines_joined(self):
        path = FIXTURES / "continuation.sp"
        region = _macro_region(path)
        result = self._make_parser(path, region)
        rc = result.cells[0]
        instances = {i.name: i for i in rc.instances}
        assert "tc1" in instances["R2"].params

    def test_title_line_skipped_when_not_directive(self, tmp_path):
        # First physical line is plain text (title) → should be consumed silently
        sp = tmp_path / "title.sp"
        sp.write_text("My Circuit Simulation Title\n.subckt inv in out\nR1 in out 1k\n.ends inv\n")
        region = _macro_region(sp)
        result = self._make_parser(sp, region)
        assert result.cells[0].name == "inv"

    def test_directive_as_first_line_not_skipped(self, tmp_path):
        sp = tmp_path / "nodirective.sp"
        sp.write_text(".subckt inv in out\nR1 in out 1k\n.ends inv\n")
        region = _macro_region(sp)
        result = self._make_parser(sp, region)
        assert result.cells[0].name == "inv"

    def test_comment_first_line_not_consumed_as_title(self, tmp_path):
        sp = tmp_path / "comment.sp"
        sp.write_text("* comment first\n.subckt buf in out\nR1 in out 1k\n.ends buf\n")
        region = _macro_region(sp)
        result = self._make_parser(sp, region)
        assert result.cells[0].name == "buf"

    def test_read_physical_line_respects_end_byte(self):
        path = FIXTURES / "minimal.sp"
        region = _macro_region(path)
        # end_byte != -1, so _read_physical_line respects the region boundary
        with open_mmap(path) as mm:
            lp = SpiceLineParser(str(path), mm, region)
            cp = SpiceChunkParser(mm, region, lp)
            lines = [ln for ln in cp if ln is not None]
        assert lines  # region produced at least one logical line

    def test_global_region_with_includes(self):
        path = FIXTURES / "with_include.sp"
        regions = list(Scanner(path, SpiceScanStrategy()).scan())
        for region in regions:
            with open_mmap(path) as mm:
                lp = SpiceLineParser(str(path), mm, region)
                cp = SpiceChunkParser(mm, region, lp)
                result = cp.parse()
                assert result is not None

    def test_title_line_consumed_for_plain_text_first_line(self, tmp_path):
        # First line is plain text (not comment, not directive) — title branch
        sp = tmp_path / "title.sp"
        sp.write_text("My Circuit Simulation\n.model nmos_tt nmos level=54\n.subckt inv in out\n.ends inv\n")
        # GLOBAL region at byte 0 contains "My Circuit Simulation\n.model nmos_tt..."
        global_regions = [r for r in Scanner(sp, SpiceScanStrategy()).scan() if r.region_type == RegionType.GLOBAL]
        first_global = global_regions[0]
        assert first_global.start_byte == 0
        with open_mmap(sp) as mm:
            lp = SpiceLineParser(str(sp), mm, first_global)
            cp = SpiceChunkParser(mm, first_global, lp)
            result = cp.parse()
        # Title line consumed silently; .model captured
        assert any(c.name == "nmos_tt" for c in result.cells)

    def test_empty_global_region_at_byte_zero_returns_early(self, tmp_path):
        sp = tmp_path / "nonempty.sp"
        sp.write_text("R1 a b 1k\n")
        empty_region = ParseRegion(filepath=str(sp), start_byte=0, end_byte=0, region_type=RegionType.GLOBAL)
        with open_mmap(sp) as mm:
            lp = SpiceLineParser(str(sp), mm, empty_region)
            cp = SpiceChunkParser(mm, empty_region, lp)
            result = cp.parse()
        assert not result.cells

    def test_whole_file_region_hits_readline_eof(self, tmp_path):
        sp = tmp_path / "small.sp"
        sp.write_text("R1 a b 1k\n")
        whole_file_region = ParseRegion(filepath=str(sp), start_byte=0, end_byte=-1, region_type=RegionType.GLOBAL)
        with open_mmap(sp) as mm:
            lp = SpiceLineParser(str(sp), mm, whole_file_region)
            cp = SpiceChunkParser(mm, whole_file_region, lp)
            result = cp.parse()
        assert result is not None

    def test_global_region_with_model_at_top_level(self):
        # models.sp has top-level .model directives → hits ChunkParser.parse else: cells.append(decl)
        path = FIXTURES / "models.sp"
        global_regions = [r for r in Scanner(path, SpiceScanStrategy()).scan() if r.region_type == RegionType.GLOBAL]
        first_global = global_regions[0]
        with open_mmap(path) as mm:
            lp = SpiceLineParser(str(path), mm, first_global)
            cp = SpiceChunkParser(mm, first_global, lp)
            result = cp.parse()
        assert any(hasattr(c, "base_type") for c in result.cells)

    def test_macro_region_with_internal_model(self):
        # models.sp .subckt has a .model inside → hits ChunkParser.parse elif macro: branch
        path = FIXTURES / "models.sp"
        region = _macro_region(path)
        with open_mmap(path) as mm:
            lp = SpiceLineParser(str(path), mm, region)
            cp = SpiceChunkParser(mm, region, lp)
            result = cp.parse()
        subckt = result.cells[0]
        assert any(hasattr(c, "base_type") for c in subckt.children)
