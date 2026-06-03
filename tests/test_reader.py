"""Tests for SpiceReader — full pipeline integration."""

# pylint: disable=missing-class-docstring,missing-function-docstring,import-outside-toplevel

from netlistio.ingestor.reader import SpiceReader
from netlistio.models.spice import NMOS, PMOS, SpiceNetlist, Subckt


class TestSpiceReaderFixtures:
    def _read(self, path, num_workers=1):
        return SpiceReader().read(path, num_workers=num_workers)

    def test_reads_minimal_fixture(self, fixture_path):
        netlist = self._read(fixture_path("minimal.sp"))
        assert isinstance(netlist, SpiceNetlist)
        assert netlist.macros.get("voltage_divider") is not None

    def test_minimal_has_correct_ports(self, fixture_path):
        netlist = self._read(fixture_path("minimal.sp"))
        sub = netlist.macros.get("voltage_divider")
        port_names = [p.name for p in sub.ports]
        assert port_names == ["in", "out", "gnd"]

    def test_reads_mosfet_fixture(self, fixture_path):
        netlist = self._read(fixture_path("mosfets.sp"))
        sub = netlist.macros.get("inv")
        instances = list(sub.instances)
        assert any(isinstance(i.definition, PMOS) for i in instances)
        assert any(isinstance(i.definition, NMOS) for i in instances)

    def test_reads_hierarchy_fixture(self, fixture_path):
        netlist = self._read(fixture_path("hierarchy.sp"))
        assert netlist.macros.get("inv") is not None
        assert netlist.macros.get("buf") is not None

    def test_hierarchy_has_top_instances(self, fixture_path):
        netlist = self._read(fixture_path("hierarchy.sp"))
        assert len(netlist.top_instances) == 1

    def test_hierarchy_buf_resolves_inv(self, fixture_path):
        netlist = self._read(fixture_path("hierarchy.sp"))
        buf = netlist.macros.get("buf")
        x_instances = list(buf.instances)
        assert all(i.definition is not None for i in x_instances)

    def test_library_only_includes_all_macros(self, fixture_path):
        netlist = self._read(fixture_path("library_only.sp"))
        assert netlist.macros.get("nand2") is not None
        assert netlist.macros.get("nor2") is not None

    def test_continuation_joins_params(self, fixture_path):
        netlist = self._read(fixture_path("continuation.sp"))
        rc = netlist.macros.get("rc_ladder")
        instances = {i.name: i for i in rc.instances}
        assert "tc1" in instances["R2"].params

    def test_models_fixture_parses_model_directives(self, fixture_path):
        netlist = self._read(fixture_path("models.sp"))
        assert netlist.macros.get("inv_fast") is not None

    def test_clean_parse_logs_no_link_errors(self, fixture_path, caplog):
        SpiceReader().read(fixture_path("minimal.sp"), num_workers=1)
        assert "errors" not in caplog.text.lower()

    def test_link_errors_logged_for_unresolved_instance(self, tmp_spice, caplog):
        sp = tmp_spice(".subckt top in out\nX1 in out nonexistent_cell\n.ends top\n")
        with caplog.at_level("WARNING"):
            SpiceReader().read(sp, num_workers=1)
        assert "errors" in caplog.text.lower()
        assert "nonexistent_cell" in caplog.text or "UNDEFINED_MODEL" in caplog.text

    def test_top_is_virtual_subckt(self, fixture_path):
        netlist = self._read(fixture_path("minimal.sp"))
        assert isinstance(netlist.top, Subckt)

    def test_cells_contains_all_definitions(self, fixture_path):
        netlist = self._read(fixture_path("library_only.sp"))
        cell_names = {c.name for c in netlist.cells}
        assert "nand2" in cell_names
        assert "nor2" in cell_names

    def test_num_workers_parameter_accepted(self, fixture_path):
        netlist = SpiceReader().read(fixture_path("minimal.sp"), num_workers=2)
        assert netlist.macros.get("voltage_divider") is not None
