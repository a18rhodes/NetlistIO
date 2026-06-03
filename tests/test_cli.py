"""Tests for the developer CLI using Click's test runner."""

# pylint: disable=missing-class-docstring,missing-function-docstring

import sys
from pathlib import Path

from click.testing import CliRunner

from netlistio.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"


class TestRegionsCommand:
    def test_shows_table_for_valid_file(self):
        result = CliRunner().invoke(cli, ["regions", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 0
        assert "MACRO" in result.output

    def test_reports_no_regions_for_empty_file(self, tmp_path):
        empty = tmp_path / "empty.sp"
        empty.write_text("")
        result = CliRunner().invoke(cli, ["regions", str(empty)])
        assert result.exit_code == 0
        assert "No regions found" in result.output

    def test_global_regions_shown(self):
        result = CliRunner().invoke(cli, ["regions", str(FIXTURES / "hierarchy.sp")])
        assert result.exit_code == 0
        assert "GLOBAL" in result.output


class TestParseCommand:
    def test_shows_macro_summary(self):
        result = CliRunner().invoke(cli, ["parse", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 0
        assert "Macros" in result.output
        assert "voltage_divider" in result.output

    def test_workers_flag_accepted(self):
        result = CliRunner().invoke(cli, ["parse", "--workers", "1", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 0

    def test_no_macros_message(self, tmp_path):
        sp = tmp_path / "empty_top.sp"
        sp.write_text("* no subckts\n")
        result = CliRunner().invoke(cli, ["parse", str(sp)])
        assert result.exit_code == 0
        assert "no subcircuit definitions found" in result.output

    def test_hierarchy_shows_two_macros(self):
        result = CliRunner().invoke(cli, ["parse", str(FIXTURES / "hierarchy.sp")])
        assert result.exit_code == 0
        assert "inv" in result.output
        assert "buf" in result.output


class TestDumpCommand:
    def test_writes_tree_to_stdout(self):
        result = CliRunner().invoke(cli, ["dump", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 0
        assert "voltage_divider" in result.output

    def test_workers_flag_accepted(self):
        result = CliRunner().invoke(cli, ["dump", "-w", "1", str(FIXTURES / "library_only.sp")])
        assert result.exit_code == 0


class TestVerbosityFlags:
    def test_default_exits_cleanly(self):
        result = CliRunner().invoke(cli, ["parse", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 0

    def test_verbose_flag_accepted(self):
        result = CliRunner().invoke(cli, ["-v", "parse", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 0

    def test_double_verbose_accepted(self):
        result = CliRunner().invoke(cli, ["-vv", "parse", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 0

    def test_quiet_flag_accepted(self):
        result = CliRunner().invoke(cli, ["-q", "parse", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 0

    def test_verbose_surfaces_link_warnings(self, tmp_path):
        sp = tmp_path / "broken.sp"
        sp.write_text(".subckt top a b\nX1 a b ghost\n.ends top\n")
        result = CliRunner().invoke(cli, ["-v", "parse", str(sp)], catch_exceptions=False)
        assert result.exit_code == 0
        assert "UNDEFINED_MODEL" in result.output or "ghost" in result.output


class TestGraphCommand:
    def test_bipartite_stats_with_subckt(self):
        result = CliRunner().invoke(
            cli, ["graph", "--stats", "--subckt", "voltage_divider", str(FIXTURES / "minimal.sp")]
        )
        assert result.exit_code == 0
        assert "Total Nets" in result.output

    def test_device_stats_with_subckt(self):
        result = CliRunner().invoke(
            cli, ["graph", "--stats", "--mode", "device", "--subckt", "voltage_divider", str(FIXTURES / "minimal.sp")]
        )
        assert result.exit_code == 0
        assert "Total Instances" in result.output

    def test_library_only_file_exits_with_hint(self):
        result = CliRunner().invoke(cli, ["graph", "--stats", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 1
        assert "Use --subckt" in result.output

    def test_unknown_subckt_exits_with_error(self):
        result = CliRunner().invoke(cli, ["graph", "--stats", "--subckt", "nonexistent", str(FIXTURES / "minimal.sp")])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_hierarchy_top_instances_bipartite(self):
        result = CliRunner().invoke(cli, ["graph", "--stats", str(FIXTURES / "hierarchy.sp")])
        assert result.exit_code == 0
        assert "Total Nets" in result.output

    def test_hierarchy_top_instances_device(self):
        result = CliRunner().invoke(cli, ["graph", "--stats", "--mode", "device", str(FIXTURES / "hierarchy.sp")])
        assert result.exit_code == 0
        assert "Total Instances" in result.output

    def test_bipartite_output_to_dot(self, tmp_path):
        output = tmp_path / "out.dot"
        result = CliRunner().invoke(
            cli,
            [
                "graph",
                "--subckt",
                "voltage_divider",
                "--output",
                str(output),
                "--no-show",
                str(FIXTURES / "minimal.sp"),
            ],
        )
        assert result.exit_code == 0

    def test_device_output_to_dot(self, tmp_path):
        output = tmp_path / "out.dot"
        result = CliRunner().invoke(
            cli,
            [
                "graph",
                "--mode",
                "device",
                "--subckt",
                "voltage_divider",
                "--output",
                str(output),
                "--no-show",
                str(FIXTURES / "minimal.sp"),
            ],
        )
        assert result.exit_code == 0


class TestToPygCommand:
    def test_saves_pt_file(self, tmp_path):
        output = tmp_path / "graph.pt"
        result = CliRunner().invoke(cli, ["to-pyg", str(FIXTURES / "hierarchy.sp"), str(output)])
        assert result.exit_code == 0
        assert output.exists()

    def test_saves_pt_file_with_subckt(self, tmp_path):
        output = tmp_path / "graph.pt"
        result = CliRunner().invoke(
            cli,
            [
                "to-pyg",
                "--subckt",
                "inv",
                str(FIXTURES / "hierarchy.sp"),
                str(output),
            ],
        )
        assert result.exit_code == 0
        assert output.exists()

    def test_exits_when_torch_not_available(self, tmp_path, monkeypatch):
        output = tmp_path / "graph.pt"
        monkeypatch.setitem(sys.modules, "torch", None)
        result = CliRunner().invoke(cli, ["to-pyg", str(FIXTURES / "hierarchy.sp"), str(output)])
        assert result.exit_code == 1

    def test_unknown_subckt_exits_with_error(self, tmp_path):
        output = tmp_path / "graph.pt"
        result = CliRunner().invoke(
            cli,
            [
                "to-pyg",
                "--subckt",
                "nonexistent",
                str(FIXTURES / "hierarchy.sp"),
                str(output),
            ],
        )
        assert result.exit_code == 1
