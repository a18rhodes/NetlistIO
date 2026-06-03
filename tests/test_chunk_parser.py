"""Tests for SpiceChunkParser — logical line assembly."""

# pylint: disable=missing-class-docstring,missing-function-docstring

from netlistio.ingestor.reader import SpiceReader
from netlistio.models.spice import SpiceNetlist


class TestContinuationLines:
    def test_continuation_joins_lines(self, tmp_spice):
        sp = """\
* test
.subckt rc in out gnd
R1 in mid 1k
+ tc1=0.001 tc2=0.0001
R2 mid out 2k
.ends rc
"""
        path = tmp_spice(sp)
        netlist = SpiceReader().read(path, num_workers=1)
        assert isinstance(netlist, SpiceNetlist)
        rc = netlist.macros.get("rc")
        assert rc is not None
        instances = list(rc.instances)
        r1 = next(i for i in instances if i.name == "R1")
        assert "tc1" in r1.params
        assert r1.params["tc1"] == "0.001"

    def test_comment_lines_filtered(self, tmp_spice):
        sp = """\
* title
.subckt test a b
* this is a comment inside subckt
R1 a b 1k
$ dollar comment
R2 a b 2k
.ends test
"""
        path = tmp_spice(sp)
        netlist = SpiceReader().read(path, num_workers=1)
        test = netlist.macros.get("test")
        instances = list(test.instances)
        assert len(instances) == 2

    def test_title_line_skipped_in_global_region(self, tmp_spice):
        sp = "this is the title line\n.subckt inv in out\nR1 in out 1k\n.ends inv\n"
        path = tmp_spice(sp)
        netlist = SpiceReader().read(path, num_workers=1)
        assert netlist.macros.get("inv") is not None

    def test_directive_first_line_not_skipped(self, tmp_spice):
        sp = ".subckt inv in out\nR1 in out 1k\n.ends inv\n"
        path = tmp_spice(sp)
        netlist = SpiceReader().read(path, num_workers=1)
        assert netlist.macros.get("inv") is not None

    def test_empty_file_parses_cleanly(self, tmp_spice):
        path = tmp_spice("")
        netlist = SpiceReader().read(path, num_workers=1)
        assert not netlist.macros

    def test_comment_only_file(self, tmp_spice):
        path = tmp_spice("* just a comment\n$ another\n")
        netlist = SpiceReader().read(path, num_workers=1)
        assert not netlist.macros
