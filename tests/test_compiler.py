"""Tests for the Compiler — iterative include resolution."""

# pylint: disable=missing-class-docstring,missing-function-docstring

from pathlib import Path

import pytest

from netlistio.ingestor.compiler import Compiler
from netlistio.ingestor.parser import Parser
from netlistio.ingestor.scanner import Scanner
from netlistio.ingestor.spice import (
    SpiceChunkParserFactory,
    SpiceLibraryProcessor,
    SpiceScanStrategy,
)


def _make_compiler(root: Path, num_workers: int = 1) -> Compiler:
    def scanner_factory(fp):
        return Scanner(fp, SpiceScanStrategy())

    def parser_factory(fp, regions):
        return Parser(fp, regions, SpiceChunkParserFactory())

    return Compiler(
        root_filepath=root,
        parser_factory=parser_factory,
        scanner_factory=scanner_factory,
        library_factory=SpiceLibraryProcessor,
        num_workers=num_workers,
    )


class TestCompilerSingleFile:
    def test_compiles_minimal_fixture(self, fixture_path):
        result = _make_compiler(fixture_path("minimal.sp")).compile()
        assert any(c.name == "voltage_divider" for c in result.cells)

    def test_compiles_library_only(self, fixture_path):
        result = _make_compiler(fixture_path("library_only.sp")).compile()
        names = {c.name for c in result.cells}
        assert "nand2" in names
        assert "nor2" in names

    def test_visited_regions_populated(self, fixture_path):
        compiler = _make_compiler(fixture_path("minimal.sp"))
        compiler.compile()
        assert len(compiler.visited_regions) > 0


class TestCompilerIncludeResolution:
    def test_lib_section_resolved(self, fixture_path):
        result = _make_compiler(fixture_path("with_include.sp")).compile()
        # .model directives from the tt section should be present
        names = {c.name for c in result.cells}
        assert "nmos_tt" in names or "inv" in names

    def test_missing_strict_include_logs_warning(self, tmp_path, caplog):
        sp = tmp_path / "strict.sp"
        sp.write_text('.include "nonexistent_file.sp"\n.subckt inv in out\n.ends inv\n')
        compiler = _make_compiler(sp)
        with caplog.at_level("WARNING"):
            compiler.compile()
        assert "Could not resolve include" in caplog.text
        assert "nonexistent_file.sp" in caplog.text

    def test_missing_nonstrict_include_is_silent(self, tmp_path, caplog):
        sp = tmp_path / "lenient.sp"
        sp.write_text("[? nonexistent_optional.sp ]\n.subckt inv in out\n.ends inv\n")
        compiler = _make_compiler(sp)
        with caplog.at_level("WARNING"):
            compiler.compile()
        assert "Could not resolve" not in caplog.text

    def test_path_resolution_relative_to_source(self, tmp_path):
        subdir = tmp_path / "cells"
        subdir.mkdir()
        lib_file = subdir / "lib.sp"
        lib_file.write_text("* lib\n.subckt leaf a b\nR1 a b 1k\n.ends leaf\n")
        top_file = tmp_path / "top.sp"
        top_file.write_text('.include "cells/lib.sp"\nXtop a b leaf\n')
        result = _make_compiler(top_file).compile()
        names = {c.name for c in result.cells}
        assert "leaf" in names

    def test_duplicate_include_not_revisited(self, tmp_path):
        lib = tmp_path / "lib.sp"
        lib.write_text(".subckt leaf a b\nR1 a b 1k\n.ends leaf\n")
        top = tmp_path / "top.sp"
        top.write_text('.include "lib.sp"\n.include "lib.sp"\nXtop a b leaf\n')
        compiler = _make_compiler(top)
        result = compiler.compile()
        leaf_cells = [c for c in result.cells if c.name == "leaf"]
        assert len(leaf_cells) == 1


class TestCompilerEdgeCases:
    def test_lib_directive_with_missing_section_logs_warning(self, tmp_path, caplog):
        lib = tmp_path / "corners.lib"
        lib.write_text(".lib tt\n.model nmos_tt nmos\n.endl tt\n")
        sp = tmp_path / "top.sp"
        sp.write_text('.lib "corners.lib" nonexistent_corner\n.subckt inv in out\n.ends inv\n')
        with caplog.at_level("WARNING"):
            _make_compiler(sp).compile()
        assert "not found" in caplog.text

    def test_absolute_path_include_resolved(self, tmp_path):
        lib = tmp_path / "absolute_lib.sp"
        lib.write_text(".subckt leaf a b\nR1 a b 1k\n.ends leaf\n")
        sp = tmp_path / "top.sp"
        sp.write_text(f'.include "{lib.resolve()}"\nXtop a b leaf\n')
        result = _make_compiler(sp).compile()
        names = {c.name for c in result.cells}
        assert "leaf" in names


class TestLibrarySectionExtraction:
    def test_section_found(self, fixture_path):
        processor = SpiceLibraryProcessor()
        section = processor.find_section(fixture_path("lib_sections.lib"), "tt")
        assert section.name == "tt"
        assert section.start_byte < section.end_byte

    def test_section_not_found_raises(self, fixture_path):
        processor = SpiceLibraryProcessor()
        with pytest.raises(ValueError, match="not found"):
            processor.find_section(fixture_path("lib_sections.lib"), "nonexistent")

    def test_both_sections_have_distinct_ranges(self, fixture_path):
        processor = SpiceLibraryProcessor()
        tt = processor.find_section(fixture_path("lib_sections.lib"), "tt")
        ff = processor.find_section(fixture_path("lib_sections.lib"), "ff")
        assert tt.start_byte != ff.start_byte
        assert tt.end_byte < ff.start_byte

    def test_missing_endl_falls_back_to_file_end(self, tmp_path):
        lib = tmp_path / "noeol.lib"
        lib.write_text(".lib tt\n.model nmos_tt nmos level=54\n")
        processor = SpiceLibraryProcessor()
        section = processor.find_section(lib, "tt")
        assert section.end_byte == lib.stat().st_size
