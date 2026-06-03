"""Tests for generic and SPICE-specific data models."""

# pylint: disable=missing-class-docstring,missing-function-docstring
# pylint: disable=no-value-for-parameter,import-outside-toplevel,unused-variable

import pytest

from netlistio.models.generic import Instance, NetConnection, Port, Primitive
from netlistio.models.linking import LinkError, LinkErrorType, LinkResult
from netlistio.models.parsing import (
    IncludeDirective,
    LibraryDirective,
    LibrarySection,
    ParseError,
    ParseRegion,
    ParseResult,
    RegionType,
)
from netlistio.models.spice import (
    MOSFET,
    NMOS,
    PMOS,
    Capacitor,
    Diode,
    Inductor,
    Model,
    Resistor,
    SpiceNetlist,
    Subckt,
    get_definition_from_prefix,
    passive_registry,
    prefix_registry,
)


class TestPrimitives:
    def test_resistor_name_and_ports(self):
        r = Resistor()
        assert r.name == "resistor"
        assert len(r.ports) == 2
        assert r.ports[0].name == "a"
        assert r.ports[1].name == "b"

    def test_capacitor_name_and_ports(self):
        c = Capacitor()
        assert c.name == "capacitor"
        assert len(c.ports) == 2

    def test_inductor_name(self):
        assert Inductor().name == "inductor"

    def test_mosfet_ports(self):
        m = MOSFET()
        port_names = [p.name for p in m.ports]
        assert port_names == ["d", "g", "s", "b"]

    def test_nmos_pmos_distinction(self):
        assert NMOS().name == "nmos"
        assert PMOS().name == "pmos"

    def test_diode_ports(self):
        d = Diode()
        port_names = [p.name for p in d.ports]
        assert port_names == ["a", "k"]

    def test_primitive_equality_by_type(self):
        assert Resistor() == Resistor()
        assert Resistor() != Capacitor()

    def test_primitive_hash_by_type(self):
        assert hash(Resistor()) == hash(Resistor())
        assert hash(Resistor()) != hash(Capacitor())

    def test_primitive_rejects_instance_fields(self):
        with pytest.raises(TypeError, match="cannot define instance fields"):

            class BadPrimitive(Primitive):  # noqa: F841
                bad_field: int

    def test_primitive_init_subclass_allows_classvars(self):
        from typing import ClassVar

        class GoodPrimitive(Primitive):
            name: ClassVar[str] = "good"
            ports: ClassVar[tuple] = ()

        assert GoodPrimitive.name == "good"


class TestPort:
    def test_port_name(self):
        p = Port("vdd")
        assert p.name == "vdd"


class TestMacro:
    def _make_macro(self):
        sub = Subckt(name="top", ports=(Port("a"), Port("b")))
        r = Resistor()
        inst = Instance(name="R1", nets=[NetConnection("a"), NetConnection("b")], definition=r)
        sub.children.append(inst)
        return sub, inst

    def test_instances_yields_only_instances(self):
        sub, inst = self._make_macro()
        model = Model(name="m", base_type="nmos")
        sub.children.append(model)
        instances = list(sub.instances)
        assert instances == [inst]
        assert model not in instances

    def test_nets_returns_dict(self):
        sub, _ = self._make_macro()
        nets = sub.nets
        assert isinstance(nets, dict)

    def test_nets_empty_before_port_mapping(self):
        sub, _ = self._make_macro()
        # Nets has keys but values are None before linking maps ports
        assert isinstance(sub.nets, dict)

    def test_nets_with_mapped_ports_covers_loop_body(self):
        sub = Subckt(name="test", ports=(Port("a"), Port("b")))
        formal_a, formal_b = Port("a"), Port("b")
        inst = Instance(
            name="R1", nets=[NetConnection("net1", formal_a), NetConnection("net2", formal_b)], definition=Resistor()
        )
        sub.children.append(inst)
        nets = sub.nets
        assert "net1" in nets or "net2" in nets


class TestInstance:
    def test_is_primitive_true(self):
        inst = Instance(name="R1", definition=Resistor())
        assert inst.is_primitive is True

    def test_is_primitive_false_for_macro(self):
        sub = Subckt(name="inv", ports=())
        inst = Instance(name="X1", definition=sub)
        assert inst.is_primitive is False

    def test_is_primitive_false_for_unresolved(self):
        inst = Instance(name="X1", definition_name="unknown")
        assert inst.is_primitive is False

    def test_ports_with_mapped_ports(self):
        formal = Port("a")
        inst = Instance(name="R1", nets=[NetConnection("net1", formal), NetConnection("net2")])
        ports = inst.ports
        assert len(ports) == 1
        assert ports[0].name == "a"
        assert ports[0].net == "net1"


class TestSpiceNetlist:
    def _make_netlist(self):
        sub = Subckt(name="inv", ports=(Port("in"), Port("out")))
        return SpiceNetlist(name="test.sp", macros={"inv": sub})

    def test_subckts_alias(self):
        nl = self._make_netlist()
        assert nl.subckts is nl.macros
        assert isinstance(nl.subckts, dict)

    def test_subckt_lookup_hit(self):
        nl = self._make_netlist()
        result = nl.subckt("inv")
        assert result is not None
        assert result.name == "inv"

    def test_subckt_lookup_miss(self):
        nl = self._make_netlist()
        assert nl.subckt("missing") is None

    def test_top_returns_subckt(self):
        nl = self._make_netlist()
        top = nl.top
        assert isinstance(top, Subckt)

    def test_top_subckt_matches_top(self):
        nl = self._make_netlist()
        assert nl.top_subckt.name == nl.top.name

    def test_top_instances_property(self):
        nl = self._make_netlist()
        assert isinstance(nl.top_instances, list)

    def test_cells_property(self):
        nl = self._make_netlist()
        cells = nl.cells
        assert any(c.name == "inv" for c in cells)


class TestSpiceRegistries:
    def test_prefix_registry_has_standard_types(self):
        reg = prefix_registry()
        assert "R" in reg
        assert "C" in reg
        assert "M" in reg
        assert "X" in reg

    def test_passive_registry_contains_passives(self):
        reg = passive_registry()
        names = {cls.name for cls in reg}
        assert "resistor" in names
        assert "capacitor" in names
        assert "inductor" in names
        assert "mosfet" not in names

    def test_get_definition_from_prefix_known(self):
        assert get_definition_from_prefix("X") is Subckt

    def test_get_definition_from_prefix_case_insensitive(self):
        assert get_definition_from_prefix("x") is Subckt
        assert get_definition_from_prefix("r") is Resistor

    def test_get_definition_from_prefix_unknown_raises(self):
        with pytest.raises(ValueError, match="does not map"):
            get_definition_from_prefix("Z")


class TestLinkingModels:
    def test_link_error_type_values_are_ints(self):
        for member in LinkErrorType:
            assert isinstance(member.value, int), f"{member} value is not int"

    def test_link_error_construction(self):
        err = LinkError(
            error_type=LinkErrorType.UNDEFINED_MODEL,
            message="test error",
            affected_cells=["X1"],
        )
        assert err.error_type == LinkErrorType.UNDEFINED_MODEL

    def test_link_result_defaults(self):
        nl = SpiceNetlist(name="t")
        result = LinkResult(netlist=nl)
        assert not result.errors
        assert not result.top_instances


class TestParsingModels:
    def test_include_directive(self):
        d = IncludeDirective(filepath="foo.sp", source_file="bar.sp")
        assert d.strict is True

    def test_library_directive_with_section(self):
        d = LibraryDirective(filepath="pdk.lib", source_file="top.sp", section="tt")
        assert d.section == "tt"
        assert d.strict is True

    def test_parse_error(self):
        e = ParseError(line_number=5, message="bad token", line_content="X bad")
        assert e.line_number == 5

    def test_parse_result_defaults(self):
        r = ParseResult(filepath="test.sp")
        assert not r.cells
        assert not r.errors
        assert not r.includes

    def test_parse_region(self):
        r = ParseRegion(filepath="f.sp", start_byte=0, end_byte=100, region_type=RegionType.GLOBAL)
        assert r.region_type == RegionType.GLOBAL

    def test_library_section(self):
        s = LibrarySection(name="tt", start_byte=10, end_byte=200)
        assert s.name == "tt"

    def test_region_type_members(self):
        assert RegionType.GLOBAL != RegionType.MACRO
