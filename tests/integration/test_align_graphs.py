"""
Structural equivalence tests against ALIGN benchmark circuits.

Validates that CircuitGraph produces a bipartite net/instance graph whose
structure and features match the representation described in:

  Kunal et al., "GANA: Graph Convolutional Network Based Automated Netlist
  Annotation for Analog Circuits," DATE 2020.

Circuits are sourced from ALIGN-analoglayout/ALIGN-public (Apache 2.0):
  https://github.com/ALIGN-analoglayout/ALIGN-public/tree/master/examples

Tests run only when --integration is passed to pytest.
"""

# pylint: disable=missing-class-docstring,missing-function-docstring

from pathlib import Path

import pytest

from netlistio.graph_analysis.circuit_graph import (
    _NET_TYPE_NAMES,
    _TERMINAL_VOCAB,
    CircuitGraph,
)
from netlistio.ingestor.reader import SpiceReader

torch = pytest.importorskip("torch", reason="torch not installed")

ALIGN = Path(__file__).parent.parent / "fixtures" / "align"
_OTHER_IDX = list(_TERMINAL_VOCAB).index("other")
_PORT_IDX = list(_NET_TYPE_NAMES).index("port")
_SIGNAL_IDX = list(_NET_TYPE_NAMES).index("signal")
_POWER_IDX = list(_NET_TYPE_NAMES).index("power")
_GROUND_IDX = list(_NET_TYPE_NAMES).index("ground")


def _load(circuit_name: str) -> tuple[CircuitGraph, object]:
    netlist = SpiceReader().read(ALIGN / f"{circuit_name}.sp", num_workers=1)
    macro = netlist.macros[circuit_name]
    cg = CircuitGraph.from_macro(macro)
    return cg, cg.to_pyg()


@pytest.mark.integration
class TestTelescopicOTA:
    """10-transistor telescopic OTA — covers NMOS cascode + PMOS load."""

    def test_device_count(self):
        cg, _ = _load("telescopic_ota")
        assert len(cg.instance_metadata) == 10

    def test_net_count(self):
        cg, _ = _load("telescopic_ota")
        assert len(cg.nets) == 15

    def test_port_net_count(self):
        # 10 declared ports: vbiasn vbiasp1 vbiasp2 vinn vinp voutn voutp id vdd 0
        cg, _ = _load("telescopic_ota")
        assert len(cg._port_nets) == 10  # pylint: disable=protected-access

    def test_bipartite_structure(self):
        _, data = _load("telescopic_ota")
        assert data["instance"].x.shape[0] == 10
        assert data["net"].x.shape[0] == 15

    def test_all_edges_have_named_terminals(self):
        # Every MOSFET has 4 uniquely-named ports (d/g/s/b) so no edge should
        # fall back to the 'other' bucket.
        _, data = _load("telescopic_ota")
        ea = data["instance", "connects_to", "net"].edge_attr
        assert int((ea.argmax(dim=1) != _OTHER_IDX).sum()) == ea.shape[0]

    def test_edge_count(self):
        # 10 MOSFETs × 4 terminals = 40 edges (duplicate nets → duplicate entries)
        _, data = _load("telescopic_ota")
        assert data["instance", "connects_to", "net"].edge_index.shape[1] == 40

    def test_edge_attr_is_one_hot(self):
        _, data = _load("telescopic_ota")
        ea = data["instance", "connects_to", "net"].edge_attr
        assert torch.all(ea.sum(dim=1) == 1.0)

    def test_net_type_one_hot(self):
        _, data = _load("telescopic_ota")
        # net_x[:, 1:] is the net-type one-hot; each net must have exactly one type
        assert torch.all(data["net"].x[:, 1:].sum(dim=1) == 1.0)

    def test_port_nets_classified_as_port(self):
        cg, data = _load("telescopic_ota")
        net_names = sorted(cg.nets)
        net_x = data["net"].x
        for i, name in enumerate(net_names):
            if name in cg._port_nets:  # pylint: disable=protected-access
                assert net_x[i, 1 + _PORT_IDX] == 1.0, f"Expected '{name}' to be port"

    def test_internal_nets_classified_as_signal(self):
        cg, data = _load("telescopic_ota")
        net_names = sorted(cg.nets)
        internal = {"net10", "net8", "net014", "net012", "net06"}
        net_x = data["net"].x
        for i, name in enumerate(net_names):
            if name in internal:
                assert net_x[i, 1 + _SIGNAL_IDX] == 1.0, f"Expected '{name}' to be signal"

    def test_reverse_edges_are_transpose(self):
        _, data = _load("telescopic_ota")
        fwd = data["instance", "connects_to", "net"].edge_index
        rev = data["net", "rev_connects_to", "instance"].edge_index
        assert torch.equal(rev, fwd.flip(0))


@pytest.mark.integration
class TestFiveTransistorOTA:
    """5-transistor OTA — simplest topology, good sanity check."""

    def test_device_count(self):
        cg, _ = _load("five_transistor_ota")
        assert len(cg.instance_metadata) == 5

    def test_net_count(self):
        cg, _ = _load("five_transistor_ota")
        # 6 port nets + 2 internal (tail, vop)
        assert len(cg.nets) == 8

    def test_edge_count(self):
        _, data = _load("five_transistor_ota")
        assert data["instance", "connects_to", "net"].edge_index.shape[1] == 20

    def test_all_edges_have_named_terminals(self):
        _, data = _load("five_transistor_ota")
        ea = data["instance", "connects_to", "net"].edge_attr
        assert int((ea.argmax(dim=1) != _OTHER_IDX).sum()) == ea.shape[0]

    def test_two_device_types(self):
        _, data = _load("five_transistor_ota")
        # nmos_rvt and pmos_rvt → one-hot dim = 2
        assert data["instance"].x.shape[1] == 2

    def test_tail_and_vop_are_signals(self):
        cg, data = _load("five_transistor_ota")
        net_names = sorted(cg.nets)
        net_x = data["net"].x
        for i, name in enumerate(net_names):
            if name in {"tail", "vop"}:
                assert net_x[i, 1 + _SIGNAL_IDX] == 1.0


@pytest.mark.integration
class TestCurrentMirrorOTA:
    """12-transistor current mirror OTA."""

    def test_device_count(self):
        cg, _ = _load("current_mirror_ota")
        assert len(cg.instance_metadata) == 12

    def test_net_count(self):
        cg, _ = _load("current_mirror_ota")
        assert len(cg.nets) == 12

    def test_edge_count(self):
        _, data = _load("current_mirror_ota")
        assert data["instance", "connects_to", "net"].edge_index.shape[1] == 48

    def test_all_edges_named(self):
        _, data = _load("current_mirror_ota")
        ea = data["instance", "connects_to", "net"].edge_attr
        assert int((ea.argmax(dim=1) != _OTHER_IDX).sum()) == ea.shape[0]


@pytest.mark.integration
class TestCascodeMirrorOTA:
    """20-transistor cascode current mirror OTA — most complex fixture."""

    def test_device_count(self):
        cg, _ = _load("cascode_current_mirror_ota")
        assert len(cg.instance_metadata) == 20

    def test_net_count(self):
        cg, _ = _load("cascode_current_mirror_ota")
        assert len(cg.nets) == 20

    def test_edge_count(self):
        _, data = _load("cascode_current_mirror_ota")
        assert data["instance", "connects_to", "net"].edge_index.shape[1] == 80

    def test_all_edges_named(self):
        _, data = _load("cascode_current_mirror_ota")
        ea = data["instance", "connects_to", "net"].edge_attr
        assert int((ea.argmax(dim=1) != _OTHER_IDX).sum()) == ea.shape[0]

    def test_net_type_one_hot(self):
        _, data = _load("cascode_current_mirror_ota")
        assert torch.all(data["net"].x[:, 1:].sum(dim=1) == 1.0)
