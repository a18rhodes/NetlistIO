"""Tests for the linker — model resolution, tree-shaking, and topo sort."""

# pylint: disable=missing-class-docstring,missing-function-docstring,no-value-for-parameter

import logging

from netlistio.ingestor.linker import link
from netlistio.ingestor.registry import ModelRegistry
from netlistio.models.generic import Instance, NetConnection, Port
from netlistio.models.linking import LinkErrorType
from netlistio.models.parsing import ParseResult
from netlistio.models.spice import Model, Resistor, SpiceNetlist, Subckt


def _parse_result(*cells, filepath="test.sp"):
    return ParseResult(filepath=filepath, cells=list(cells))


def _link(*cells, registry=None):
    if registry is None:
        registry = ModelRegistry()
    return link(_parse_result(*cells), registry, SpiceNetlist)


class TestBasicLinking:
    def test_links_instance_to_macro(self):
        sub = Subckt(name="inv", ports=(Port("in"), Port("out")))
        inst = Instance(name="X1", nets=[NetConnection("net_a"), NetConnection("net_b")], definition_name="inv")
        result = _link(sub, inst)
        assert result.netlist.macros.get("inv") is not None
        assert inst.definition is sub

    def test_maps_ports_positionally(self):
        sub = Subckt(name="buf", ports=(Port("in"), Port("out")))
        inst = Instance(name="X1", nets=[NetConnection("net_a"), NetConnection("net_b")], definition_name="buf")
        _link(sub, inst)
        port_names = [p for _, p in inst.nets]
        assert any(p and p.name == "in" for p in port_names)

    def test_links_instance_to_model(self):
        model = Model(name="nmos_fast", base_type="nmos")
        inst = Instance(name="M1", nets=[NetConnection("d"), NetConnection("g")], definition_name="nmos_fast")
        _link(model, inst)
        # Model resolves as the instance definition. Models are not Primitives so
        # they don't appear in netlist.primitives, but the reference is wired.
        assert inst.definition is model

    def test_top_instances_collected(self):
        r = Resistor()
        inst = Instance(name="R1", nets=[NetConnection("a"), NetConnection("b")], definition=r)
        result = _link(inst)
        assert len(result.top_instances) == 1

    def test_primitives_collected_from_instances(self):
        r = Resistor()
        inst = Instance(name="R1", definition=r)
        result = _link(inst)
        assert len(result.netlist.primitives) == 1


class TestTreeShaking:
    def test_unreachable_macro_excluded(self):
        used = Subckt(name="used", ports=(Port("a"),))
        unused = Subckt(name="unused", ports=(Port("b"),))
        inst = Instance(name="X1", nets=[NetConnection("net")], definition_name="used")
        result = _link(used, unused, inst)
        assert "used" in result.netlist.macros
        assert "unused" not in result.netlist.macros

    def test_library_only_includes_all_macros(self):
        sub1 = Subckt(name="nand2", ports=(Port("a"), Port("b"), Port("out")))
        sub2 = Subckt(name="nor2", ports=(Port("a"), Port("b"), Port("out")))
        result = _link(sub1, sub2)
        assert "nand2" in result.netlist.macros
        assert "nor2" in result.netlist.macros

    def test_recursive_traversal_includes_transitive_deps(self):
        leaf = Subckt(name="leaf", ports=(Port("a"),))
        mid = Subckt(name="mid", ports=(Port("a"),))
        mid_inst = Instance(name="X1", nets=[NetConnection("a")], definition_name="leaf")
        mid.children.append(mid_inst)
        top_inst = Instance(name="X2", nets=[NetConnection("a")], definition_name="mid")
        result = _link(leaf, mid, top_inst)
        assert "leaf" in result.netlist.macros
        assert "mid" in result.netlist.macros


class TestErrors:
    def test_undefined_model_produces_error(self):
        inst = Instance(name="X1", nets=[], definition_name="missing_cell")
        result = _link(inst)
        assert any(e.error_type == LinkErrorType.UNDEFINED_MODEL for e in result.errors)

    def test_duplicate_definition_produces_error(self):
        sub1 = Subckt(name="inv", ports=())
        sub2 = Subckt(name="inv", ports=())
        result = _link(sub1, sub2)
        assert any(e.error_type == LinkErrorType.DUPLICATE_DEFINITION for e in result.errors)

    def test_unnamed_cell_produces_error(self):
        model = Model(name=None, base_type="nmos")
        result = _link(model)
        assert any(e.error_type == LinkErrorType.UNNAMED_CELL for e in result.errors)


class TestTopologicalSort:
    def test_sort_respects_dependency_order(self):
        leaf = Subckt(name="leaf", ports=(Port("x"),))
        parent = Subckt(name="parent", ports=(Port("x"),))
        child_inst = Instance(name="X1", nets=[NetConnection("x")], definition=leaf)
        parent.children.append(child_inst)
        top_inst = Instance(name="X2", nets=[NetConnection("x")], definition_name="parent")
        result = _link(leaf, parent, top_inst)
        macro_names = list(result.netlist.macros.keys())
        assert macro_names.index("leaf") < macro_names.index("parent")

    def test_cycle_produces_error(self):
        a = Subckt(name="a", ports=(Port("x"),))
        b = Subckt(name="b", ports=(Port("x"),))
        inst_a_in_b = Instance(name="X1", nets=[NetConnection("x")], definition=a)
        inst_b_in_a = Instance(name="X2", nets=[NetConnection("x")], definition=b)
        a.children.append(inst_b_in_a)
        b.children.append(inst_a_in_b)
        top = Instance(name="Xtop", nets=[NetConnection("x")], definition_name="a")
        result = _link(a, b, top)
        assert any(e.error_type == LinkErrorType.CIRCULAR_DEPENDENCY for e in result.errors)

    def test_port_mismatch_does_not_crash(self):
        sub = Subckt(name="mismatch", ports=(Port("a"), Port("b"), Port("c")))
        inst = Instance(name="X1", nets=[NetConnection("net1"), NetConnection("net2")], definition_name="mismatch")
        _link(sub, inst)
        assert inst.definition is sub

    def test_port_mismatch_logs_warning(self, caplog):
        sub = Subckt(name="three_port", ports=(Port("a"), Port("b"), Port("c")))
        inst = Instance(name="X1", nets=[NetConnection("net1"), NetConnection("net2")], definition_name="three_port")
        with caplog.at_level(logging.WARNING, logger="netlistio.ingestor.linker"):
            _link(sub, inst)
        assert any("mismatch" in record.message.lower() for record in caplog.records)

    def test_port_mismatch_leaves_nets_unmapped(self):
        sub = Subckt(name="two_port", ports=(Port("a"), Port("b")))
        inst = Instance(name="X1", nets=[NetConnection("net1")], definition_name="two_port")
        _link(sub, inst)
        assert all(p is None for _, p in inst.nets)

    def test_zero_connection_instance_logs_warning(self, caplog):
        sub = Subckt(name="has_ports", ports=(Port("a"),))
        inst = Instance(name="X1", nets=[], definition_name="has_ports")
        with caplog.at_level(logging.WARNING, logger="netlistio.ingestor.linker"):
            _link(sub, inst)
        assert any("mismatch" in record.message.lower() for record in caplog.records)
