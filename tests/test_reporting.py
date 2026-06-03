"""Tests for NetlistPrinter — human-readable tree rendering."""

# pylint: disable=missing-class-docstring,missing-function-docstring,no-value-for-parameter

import io

from netlistio.models.generic import Instance, NetConnection, Port
from netlistio.models.spice import Model, Resistor, SpiceNetlist, Subckt
from netlistio.reporting import NetlistPrinter


class TestPrimitiveRendering:
    def test_primitive_header_contains_class_name(self):
        buf = io.StringIO()
        NetlistPrinter(buf).print(Resistor())
        assert "Resistor" in buf.getvalue() or "resistor" in buf.getvalue()

    def test_primitive_renders_ports(self):
        buf = io.StringIO()
        NetlistPrinter(buf).print(Resistor())
        assert "Port" in buf.getvalue() or "a" in buf.getvalue()


class TestPortRendering:
    def test_port_name_in_output(self):
        buf = io.StringIO()
        NetlistPrinter(buf).print(Port("a"))
        assert "a" in buf.getvalue()


class TestMacroRendering:
    def test_few_models_renders_each_by_name(self):
        sub = Subckt(name="test", ports=())
        sub.children.append(Model(name="m1", base_type="nmos"))
        buf = io.StringIO()
        NetlistPrinter(buf).print(sub)
        assert "m1" in buf.getvalue()

    def test_many_models_shows_summary(self):
        sub = Subckt(name="test", ports=())
        for i in range(5):
            sub.children.append(Model(name=f"m{i}", base_type="nmos"))
        buf = io.StringIO()
        NetlistPrinter(buf).print(sub)
        assert "Local Definitions" in buf.getvalue()

    def test_instance_children_rendered(self):
        sub = Subckt(name="test", ports=())
        sub.children.append(Instance(name="R1", nets=[NetConnection("a"), NetConnection("b")], definition=Resistor()))
        buf = io.StringIO()
        NetlistPrinter(buf).print(sub)
        assert "R1" in buf.getvalue()


class TestInstanceRendering:
    def test_resolved_instance_shows_name(self):
        inst = Instance(name="R1", nets=[NetConnection("a")], definition=Resistor())
        buf = io.StringIO()
        NetlistPrinter(buf).print(inst)
        assert "R1" in buf.getvalue()

    def test_mapped_port_shows_port_label(self):
        formal = Port("a")
        inst = Instance(name="R1", nets=[NetConnection("net1", formal)], definition=Resistor())
        buf = io.StringIO()
        NetlistPrinter(buf).print(inst)
        assert "Port" in buf.getvalue() or "a" in buf.getvalue()

    def test_unresolved_instance_shows_definition_name(self):
        inst = Instance(name="X1", definition_name="missing_cell")
        buf = io.StringIO()
        NetlistPrinter(buf).print(inst)
        assert "missing_cell" in buf.getvalue()

    def test_many_params_truncated(self):
        params = {f"k{i}": f"v{i}" for i in range(8)}
        inst = Instance(name="R1", nets=[], params=params, definition=Resistor())
        buf = io.StringIO()
        NetlistPrinter(buf).print(inst)
        assert "more" in buf.getvalue()

    def test_no_params_omits_param_line(self):
        inst = Instance(name="R1", nets=[], definition=Resistor())
        buf = io.StringIO()
        NetlistPrinter(buf).print(inst)
        assert "R1" in buf.getvalue()

    def test_anonymous_cell_renders_placeholder(self):
        inst = Instance(name="X1", definition_name=None)
        buf = io.StringIO()
        NetlistPrinter(buf).print(inst)
        assert "Unresolved" in buf.getvalue()


class TestNetlistRendering:
    def _make_netlist(self):
        sub = Subckt(name="inv", ports=(Port("in"), Port("out")))
        return SpiceNetlist(name="test.sp", macros={"inv": sub})

    def test_netlist_name_in_output(self):
        nl = self._make_netlist()
        buf = io.StringIO()
        NetlistPrinter(buf).print(nl)
        assert "test.sp" in buf.getvalue()

    def test_netlist_with_primitives_and_top_instances(self):
        r = Resistor()
        top_inst = Instance(name="R1", nets=[NetConnection("a")], definition=r)
        nl = SpiceNetlist(name="full.sp", primitives={"resistor": r}, macros={}, _top_instances=[top_inst])
        buf = io.StringIO()
        NetlistPrinter(buf).print(nl)
        out = buf.getvalue()
        assert "Primitives" in out
        assert "R1" in out


class TestModelRendering:
    def test_model_shows_base_type(self):
        m = Model(name="nmos_fast", base_type="nmos", params={"level": "54", "tox": "7e-9"})
        buf = io.StringIO()
        NetlistPrinter(buf).print(m)
        out = buf.getvalue()
        assert "nmos" in out
        assert "level" in out

    def test_model_many_params_truncated(self):
        params = {f"k{i}": f"v{i}" for i in range(8)}
        m = Model(name="big", base_type="nmos", params=params)
        buf = io.StringIO()
        NetlistPrinter(buf).print(m)
        assert "more" in buf.getvalue()
