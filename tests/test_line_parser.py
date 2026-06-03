"""Tests for SpiceLineParser — instance, declaration, and include parsing."""

# pylint: disable=missing-class-docstring,missing-function-docstring
# pylint: disable=protected-access,attribute-defined-outside-init

import mmap

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from netlistio.ingestor.spice import SpiceLineParser
from netlistio.models.generic import Instance
from netlistio.models.parsing import ParseRegion, RegionType
from netlistio.models.spice import (
    MOSFET,
    NMOS,
    PMOS,
    Capacitor,
    Diode,
    Inductor,
    Model,
    Resistor,
    Subckt,
)


def _make_parser(content: str = "* placeholder\n") -> SpiceLineParser:
    """Creates a SpiceLineParser over an anonymous in-memory map.

    These tests drive the line-level parse methods directly with string input,
    so the map is never read; an anonymous map avoids any tempfile or fd leak.
    """
    data = content.encode()
    mm = mmap.mmap(-1, len(data))
    mm.write(data)
    mm.seek(0)
    region = ParseRegion(filepath="<test>", start_byte=0, end_byte=-1, region_type=RegionType.GLOBAL)
    return SpiceLineParser("<test>", mm, region)


class TestParseInstance:
    def setup_method(self):
        self.parser = _make_parser()

    def test_resistor(self):
        inst = self.parser.parse_instance("R1 a b 10k")
        assert isinstance(inst, Instance)
        assert inst.name == "R1"
        assert isinstance(inst.definition, Resistor)
        assert "value" in inst.params

    def test_capacitor(self):
        inst = self.parser.parse_instance("C1 a b 100n")
        assert inst is not None
        assert isinstance(inst.definition, Capacitor)

    def test_inductor(self):
        inst = self.parser.parse_instance("L1 a b 10u")
        assert inst is not None
        assert isinstance(inst.definition, Inductor)

    def test_diode(self):
        inst = self.parser.parse_instance("D1 anode cathode 1N4148")
        assert inst is not None
        assert isinstance(inst.definition, Diode)

    def test_nmos_detected_from_model_name(self):
        inst = self.parser.parse_instance("M1 d g s b nmos w=1u l=100n")
        assert isinstance(inst.definition, NMOS)

    def test_pmos_detected_from_model_name(self):
        inst = self.parser.parse_instance("M1 d g s b pmos w=2u l=100n")
        assert isinstance(inst.definition, PMOS)

    def test_nfet_suffix_detected(self):
        inst = self.parser.parse_instance("M1 d g s b sky130_nfet_01v8 w=1u l=150n")
        assert isinstance(inst.definition, NMOS)

    def test_pfet_suffix_detected(self):
        inst = self.parser.parse_instance("M1 d g s b sky130_pfet_01v8 w=2u l=150n")
        assert isinstance(inst.definition, PMOS)

    def test_nmos_detected_from_startswith_n(self):
        inst = self.parser.parse_instance("M1 d g s b nfet_01v8_hvt w=1u l=150n")
        assert isinstance(inst.definition, NMOS)

    def test_pmos_detected_from_startswith_p(self):
        inst = self.parser.parse_instance("M1 d g s b pfet_01v8_hvt w=2u l=150n")
        assert isinstance(inst.definition, PMOS)

    def test_nmos_startswith_n_no_keyword(self):
        inst = self.parser.parse_instance("M1 d g s b n_transistor w=1u l=100n")
        assert isinstance(inst.definition, NMOS)

    def test_pmos_startswith_p_no_keyword(self):
        inst = self.parser.parse_instance("M1 d g s b p_transistor w=2u l=100n")
        assert isinstance(inst.definition, PMOS)

    def test_generic_mosfet_fallback(self):
        inst = self.parser.parse_instance("M1 d g s b unknown_model w=1u l=100n")
        assert isinstance(inst.definition, MOSFET)

    def test_subckt_instance(self):
        inst = self.parser.parse_instance("X1 a b vdd vss inv")
        assert inst is not None
        assert inst.definition is None
        assert inst.definition_name == "inv"
        assert any(n == "a" for n, _ in inst.nets)

    def test_key_value_params_extracted(self):
        inst = self.parser.parse_instance("R1 a b r=10k tc1=0.001")
        assert inst is not None
        assert "r" in inst.params
        assert inst.params["tc1"] == "0.001"

    def test_equals_normalization(self):
        inst = self.parser.parse_instance("R1 a b r = 10k")
        assert inst is not None
        assert "r" in inst.params

    def test_returns_none_for_comment(self):
        assert self.parser.parse_instance("* this is a comment") is None

    def test_returns_none_for_too_few_tokens(self):
        assert self.parser.parse_instance("R1") is None

    def test_returns_none_for_unknown_prefix(self):
        assert self.parser.parse_instance("Z1 a b some_model") is None


class TestParseDeclaration:
    def setup_method(self):
        self.parser = _make_parser()

    def test_subckt_declaration(self):
        decl = self.parser.parse_declaration(".SUBCKT inv in out vdd vss")
        assert isinstance(decl, Subckt)
        assert decl.name == "inv"
        port_names = [p.name for p in decl.ports]
        assert port_names == ["in", "out", "vdd", "vss"]

    def test_subckt_case_insensitive(self):
        decl = self.parser.parse_declaration(".subckt buf a b c d")
        assert isinstance(decl, Subckt)

    def test_subckt_filters_params_from_ports(self):
        decl = self.parser.parse_declaration(".subckt opamp inp inn out vdd=3.3")
        port_names = [p.name for p in decl.ports]
        assert "vdd=3.3" not in port_names

    def test_model_declaration(self):
        decl = self.parser.parse_declaration(".model nmos_fast nmos level=54 tox=7e-9")
        assert isinstance(decl, Model)
        assert decl.name == "nmos_fast"
        assert decl.base_type == "nmos"
        assert decl.params["level"] == "54"

    def test_model_no_params(self):
        decl = self.parser.parse_declaration(".model bare_d diode")
        assert isinstance(decl, Model)
        assert not decl.params

    def test_model_valueless_flag(self):
        decl = self.parser.parse_declaration(".model m1 nmos FLAG")
        assert isinstance(decl, Model)
        assert decl.params.get("FLAG") == "true"

    def test_returns_none_for_instance(self):
        assert self.parser.parse_declaration("R1 a b 10k") is None

    def test_returns_none_for_comment(self):
        assert self.parser.parse_declaration("* comment") is None

    def test_subckt_with_no_name_returns_none(self):
        assert self.parser.parse_declaration(".SUBCKT") is None


class TestParseInclude:
    def setup_method(self):
        self.parser = _make_parser()

    def test_include_quoted(self):
        result = self.parser.parse_include('.include "models/pdk.sp"')
        assert result is not None
        assert result.filepath == "models/pdk.sp"

    def test_include_unquoted(self):
        result = self.parser.parse_include(".include models/pdk.sp")
        assert result is not None
        assert "pdk.sp" in result.filepath

    def test_lib_with_section(self):
        result = self.parser.parse_include('.lib "process.lib" tt')
        assert result is not None
        assert result.section == "tt"
        assert "process.lib" in result.filepath

    def test_lib_without_section(self):
        result = self.parser.parse_include('.lib "process.lib"')
        assert result is not None

    def test_cadence_strict_include(self):
        result = self.parser.parse_include("[! /path/to/file.spi ]")
        assert result is not None
        assert result.strict is True

    def test_cadence_lenient_include(self):
        result = self.parser.parse_include("[? /path/to/optional.spi ]")
        assert result is not None
        assert result.strict is False

    def test_returns_none_for_non_include(self):
        assert self.parser.parse_include("R1 a b 10k") is None
        assert self.parser.parse_include("* comment") is None

    def test_is_value_numeric(self):
        assert self.parser._is_value("100n") is True
        assert self.parser._is_value("1.5e-7") is True
        assert self.parser._is_value("-3.3") is True
        assert self.parser._is_value("+5") is True
        assert self.parser._is_value("nmos") is False
        assert self.parser._is_value("") is False


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

_IDENTIFIER = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"), min_size=1
)
_PARAM_VALUE = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="._-"), min_size=1
)


@given(st.lists(_IDENTIFIER, min_size=0, max_size=10))
@settings(max_examples=200)
def test_extract_params_removes_all_kv_tokens(identifiers):
    """After _extract_params, no token with '=' remains in the list."""
    parser = _make_parser()
    kv_tokens = [f"{k}={v}" for k, v in zip(identifiers[::2], identifiers[1::2])]
    plain_tokens = identifiers[len(kv_tokens) * 2 :]
    tokens = kv_tokens + plain_tokens
    params = {}
    parser._extract_params(tokens, params)
    assert not any("=" in t for t in tokens)


@given(st.lists(_IDENTIFIER, min_size=0, max_size=10))
@settings(max_examples=200)
def test_extract_params_preserves_plain_tokens(identifiers):
    """_extract_params does not remove tokens without '='."""
    parser = _make_parser()
    tokens = list(identifiers)
    params = {}
    parser._extract_params(tokens, params)
    for ident in identifiers:
        if "=" not in ident:
            assert ident in tokens


@given(st.text(min_size=1).filter(lambda s: s[0].isdigit()))
@settings(max_examples=200)
def test_is_value_true_for_digit_leading(token):
    """Any token starting with a digit is a value token."""
    assert _make_parser()._is_value(token) is True


@given(st.text(min_size=1).filter(lambda s: s[0].isalpha() and s[0] not in "eE"))
@settings(max_examples=200)
def test_is_value_false_for_alpha_leading(token):
    """Any token starting with a plain letter is not a value token."""
    assert _make_parser()._is_value(token) is False


@given(
    st.lists(
        _IDENTIFIER.filter(lambda s: "=" not in s),
        min_size=2,
        max_size=8,
    )
)
@settings(max_examples=200)
def test_separate_nets_from_model_last_token_is_definition(tokens):
    """The last token always becomes the definition name; the rest become net entries.

    Duplicate net names produce duplicate entries — two terminals tied to the same
    net are preserved so the linker can assign formal ports by position.
    """
    parser = _make_parser()
    nets_list, definition_name = parser._separate_nets_from_model(list(tokens), None)
    assert definition_name == tokens[-1]
    assert [n for n, _ in nets_list] == tokens[:-1]


@pytest.mark.parametrize(
    "model_name,expected",
    [
        ("nmos", NMOS),
        ("NMOS", NMOS),
        ("nfet_01v8", NMOS),
        ("sky130_nfet_04v2", NMOS),
        ("n_fet_hvt", NMOS),
        ("pmos", PMOS),
        ("pfet_01v8", PMOS),
        ("p_transistor", PMOS),
        ("unknown", MOSFET),
        ("mosfet_generic", MOSFET),
    ],
)
def test_classify_mosfet_heuristic(model_name, expected):
    result = _make_parser()._classify_mosfet(model_name)
    assert isinstance(result, expected)
