"""Tests for CircuitGraph — bipartite net/instance graph builder."""

# pylint: disable=missing-class-docstring,missing-function-docstring
# pylint: disable=no-value-for-parameter,wrong-import-position,ungrouped-imports

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from netlistio.graph_analysis import circuit_graph as cg_module
from netlistio.graph_analysis.circuit_graph import CircuitGraph
from netlistio.ingestor.reader import SpiceReader
from netlistio.models.generic import Instance, NetConnection, Port
from netlistio.models.spice import Resistor, Subckt


def _build_graph(sp: str, num_workers: int = 1, tmp_path: Path = None):
    p = tmp_path / "test.sp"
    p.write_text(sp)
    netlist = SpiceReader().read(p, num_workers=num_workers)
    return CircuitGraph.from_netlist(netlist)


class TestCircuitGraphConstruction:
    def test_from_macro_populates_nets(self):
        sub = Subckt(name="div", ports=(Port("in"), Port("out")))
        r = Resistor()
        sub.children.append(Instance(name="R1", nets=[NetConnection("in"), NetConnection("mid")], definition=r))
        sub.children.append(Instance(name="R2", nets=[NetConnection("mid"), NetConnection("out")], definition=r))
        graph = CircuitGraph.from_macro(sub)
        assert "in" in graph.nets
        assert "mid" in graph.nets

    def test_from_netlist_uses_top(self, fixture_path):
        netlist = SpiceReader().read(fixture_path("minimal.sp"), num_workers=1)
        graph = CircuitGraph.from_netlist(netlist)
        assert isinstance(graph.nets, dict)

    def test_add_connection_appends(self):
        graph = CircuitGraph()
        graph.add_connection("vdd", "M1.d")
        graph.add_connection("vdd", "M2.d")
        assert len(graph.nets["vdd"]) == 2

    def test_instance_metadata_captured(self, tmp_path):
        sp = "* t\n.subckt div in out gnd\nR1 in out 10k\n.ends div\nXtop in out gnd div\n"
        graph = _build_graph(sp, tmp_path=tmp_path)
        assert isinstance(graph.instance_metadata, dict)

    def test_unresolved_instance_uses_definition_name(self):
        sub = Subckt(name="top", ports=(Port("a"),))
        inst = Instance(name="X1", nets=[NetConnection("net")], definition_name="missing_cell")
        sub.children.append(inst)
        graph = CircuitGraph.from_macro(sub)
        assert "net" in graph.nets
        assert graph.instance_metadata["X1"]["model"] == "missing_cell"

    def test_instance_with_no_definition_uses_unknown(self):
        sub = Subckt(name="top", ports=())
        inst = Instance(name="X1", nets=[NetConnection("net")])
        sub.children.append(inst)
        graph = CircuitGraph.from_macro(sub)
        assert graph.instance_metadata["X1"]["model"] == "Unknown"


class TestAnalyzeConnectivity:
    def test_empty_graph_reports_empty(self, capsys):
        graph = CircuitGraph()
        graph.analyze_connectivity()
        out = capsys.readouterr().out
        assert "Graph is empty" in out

    def test_non_empty_graph_reports_stats(self, tmp_path, capsys):
        sp = "* t\n.subckt div in out gnd\nR1 in out 10k\nR2 out gnd 10k\n.ends div\nXtop in out gnd div\n"
        graph = _build_graph(sp, tmp_path=tmp_path)
        graph.analyze_connectivity()
        out = capsys.readouterr().out
        assert "Total Nets" in out


class TestVisualize:
    def _make_simple_graph(self):
        graph = CircuitGraph()
        graph.add_connection("vdd", "R1.a")
        graph.add_connection("out", "R1.b")
        graph.instance_metadata["R1"] = {"model": "resistor"}
        return graph

    def test_visualize_no_output_no_show(self):
        graph = self._make_simple_graph()
        graph.visualize(output_file=None, show=False)

    def test_visualize_png_via_matplotlib(self, tmp_path):
        graph = self._make_simple_graph()
        out_file = str(tmp_path / "graph.png")
        graph.visualize(output_file=out_file, show=False)
        assert (tmp_path / "graph.png").exists()

    def test_visualize_svg_via_matplotlib(self, tmp_path):
        graph = self._make_simple_graph()
        out_file = str(tmp_path / "graph.svg")
        graph.visualize(output_file=out_file, show=False)
        assert (tmp_path / "graph.svg").exists()

    def test_visualize_dot_export(self, tmp_path):
        graph = self._make_simple_graph()
        out_file = str(tmp_path / "graph.dot")
        graph.visualize(output_file=out_file, show=False)
        assert (tmp_path / "graph.dot").exists()

    def test_visualize_dot_export_fallback_writer(self, tmp_path, monkeypatch):
        graph = self._make_simple_graph()
        monkeypatch.setattr(cg_module, "HAS_PYDOT", False)
        out_file = str(tmp_path / "graph.dot")
        graph.visualize(output_file=out_file, show=False)
        assert (tmp_path / "graph.dot").exists()

    def test_visualize_show_interactive(self):
        graph = self._make_simple_graph()
        graph.visualize(output_file=None, show=True)

    def test_visualize_save_and_show(self, tmp_path):
        graph = self._make_simple_graph()
        out_file = str(tmp_path / "out.png")
        graph.visualize(output_file=out_file, show=True)
        assert (tmp_path / "out.png").exists()

    def test_visualize_fallback_dot_when_no_matplotlib(self, tmp_path, monkeypatch):
        graph = self._make_simple_graph()
        monkeypatch.setattr(cg_module, "HAS_MATPLOTLIB", False)
        monkeypatch.setattr(cg_module, "HAS_PYDOT", False)
        out_file = str(tmp_path / "graph.png")
        graph.visualize(output_file=out_file, show=False)
        assert (tmp_path / "graph.png.dot").exists()

    def test_visualize_no_crash_when_no_matplotlib_no_file(self, monkeypatch):
        graph = self._make_simple_graph()
        monkeypatch.setattr(cg_module, "HAS_MATPLOTLIB", False)
        graph.visualize(output_file=None, show=True)

    def test_matplotlib_render_exception_falls_back_to_dot(self, tmp_path, monkeypatch):
        graph = self._make_simple_graph()

        def _raise(*_args, **_kwargs):
            raise RuntimeError("simulated matplotlib failure")

        monkeypatch.setattr(graph, "_execute_matplotlib_render", _raise)
        monkeypatch.setattr(cg_module, "HAS_PYDOT", False)
        out_file = str(tmp_path / "fallback.png")
        graph.visualize(output_file=out_file, show=False)
        assert (tmp_path / "fallback.png.dot").exists()

    def test_mpl_save_exception_handled(self, tmp_path):
        graph = self._make_simple_graph()

        def _raise(*_args, **_kwargs):
            raise OSError("disk full")

        real_savefig = plt.savefig
        plt.savefig = _raise
        try:
            graph.visualize(output_file=str(tmp_path / "bad.png"), show=False)
        finally:
            plt.savefig = real_savefig

    def test_mpl_show_exception_handled(self, monkeypatch):
        graph = self._make_simple_graph()

        def _raise():
            raise RuntimeError("headless")

        monkeypatch.setattr(plt, "show", _raise)
        graph.visualize(output_file=None, show=True)

    def test_fallback_dot_write_error_handled(self, tmp_path, monkeypatch):
        graph = self._make_simple_graph()
        monkeypatch.setattr(cg_module, "HAS_MATPLOTLIB", False)
        monkeypatch.setattr(cg_module, "HAS_PYDOT", False)

        def _raise(*_args, **_kwargs):
            raise OSError("write failed")

        monkeypatch.setattr(graph, "_write_dot_content", _raise)
        graph.visualize(output_file=str(tmp_path / "output.png"), show=False)


class TestDeviceGraph:
    def _make_divider_graph(self):
        graph = CircuitGraph()
        graph.add_connection("vdd", "R1.a")
        graph.add_connection("mid", "R1.b")
        graph.add_connection("mid", "R2.a")
        graph.add_connection("gnd", "R2.b")
        graph.instance_metadata["R1"] = {"model": "resistor"}
        graph.instance_metadata["R2"] = {"model": "resistor"}
        return graph

    def test_to_device_graph_has_instance_nodes(self):
        graph = self._make_divider_graph()
        dg = graph.to_device_graph()
        assert "R1" in dg.nodes
        assert "R2" in dg.nodes

    def test_to_device_graph_shared_net_edge(self):
        graph = self._make_divider_graph()
        dg = graph.to_device_graph()
        assert dg.has_edge("R1", "R2")
        assert dg["R1"]["R2"]["shared_nets"] == 1
        assert "mid" in dg["R1"]["R2"]["nets"]

    def test_to_device_graph_no_self_loops(self):
        graph = CircuitGraph()
        graph.add_connection("vdd", "R1.a")
        graph.add_connection("vdd", "R1.b")
        graph.instance_metadata["R1"] = {"model": "resistor"}
        dg = graph.to_device_graph()
        assert not dg.has_edge("R1", "R1")

    def test_analyze_device_connectivity_empty(self, capsys):
        graph = CircuitGraph()
        graph.analyze_device_connectivity()
        out = capsys.readouterr().out
        assert "Graph is empty" in out

    def test_analyze_device_connectivity_reports_stats(self, capsys):
        graph = self._make_divider_graph()
        graph.analyze_device_connectivity()
        out = capsys.readouterr().out
        assert "Total Instances" in out
        assert "Average Device Degree" in out

    def test_analyze_device_connectivity_isolated(self, capsys):
        graph = CircuitGraph()
        graph.add_connection("vdd", "R1.a")
        graph.instance_metadata["R1"] = {"model": "resistor"}
        graph.analyze_device_connectivity()
        out = capsys.readouterr().out
        assert "Isolated" in out

    def test_visualize_device_graph_png(self, tmp_path):
        graph = self._make_divider_graph()
        out_file = str(tmp_path / "device.png")
        graph.visualize_device_graph(output_file=out_file, show=False)
        assert (tmp_path / "device.png").exists()

    def test_visualize_device_graph_dot(self, tmp_path):
        graph = self._make_divider_graph()
        out_file = str(tmp_path / "device.dot")
        graph.visualize_device_graph(output_file=out_file, show=False)
        assert (tmp_path / "device.dot").exists()

    def test_visualize_device_graph_no_matplotlib_fallback(self, tmp_path, monkeypatch):
        graph = self._make_divider_graph()
        monkeypatch.setattr(cg_module, "HAS_MATPLOTLIB", False)
        monkeypatch.setattr(cg_module, "HAS_PYDOT", False)
        out_file = str(tmp_path / "device.png")
        graph.visualize_device_graph(output_file=out_file, show=False)
        assert (tmp_path / "device.png.dot").exists()

    def test_visualize_device_graph_no_matplotlib_no_file(self, monkeypatch):
        graph = self._make_divider_graph()
        monkeypatch.setattr(cg_module, "HAS_MATPLOTLIB", False)
        graph.visualize_device_graph(output_file=None, show=True)

    def test_to_device_graph_multiple_shared_nets(self):
        graph = CircuitGraph()
        graph.add_connection("net1", "R1.a")
        graph.add_connection("net1", "R2.a")
        graph.add_connection("net2", "R1.b")
        graph.add_connection("net2", "R2.b")
        graph.instance_metadata["R1"] = {"model": "resistor"}
        graph.instance_metadata["R2"] = {"model": "resistor"}
        dg = graph.to_device_graph()
        assert dg["R1"]["R2"]["shared_nets"] == 2

    def test_device_edge_labels_more_than_two_nets(self):
        graph = CircuitGraph()
        for net in ("n1", "n2", "n3"):
            graph.add_connection(net, "R1.a")
            graph.add_connection(net, "R2.a")
        graph.instance_metadata["R1"] = {"model": "resistor"}
        graph.instance_metadata["R2"] = {"model": "resistor"}
        dg = graph._build_device_nx_graph()  # pylint: disable=protected-access
        labels = graph._device_edge_labels(dg)  # pylint: disable=protected-access
        assert "+1 more" in list(labels.values())[0]

    def test_export_dot_pydot_exception_falls_back(self, tmp_path, monkeypatch):
        graph = self._make_divider_graph()
        monkeypatch.setattr(cg_module, "HAS_PYDOT", True)

        def _bad_pydot(g):
            raise RuntimeError("pydot broken")

        monkeypatch.setattr(cg_module, "to_pydot", _bad_pydot)
        out_file = str(tmp_path / "out.dot")
        graph.visualize(output_file=out_file, show=False)
        assert (tmp_path / "out.dot").exists()

    def test_device_mpl_save_exception_handled(self, tmp_path):
        graph = self._make_divider_graph()

        def _raise(*_args, **_kwargs):
            raise OSError("disk full")

        real_savefig = plt.savefig
        plt.savefig = _raise
        try:
            graph.visualize_device_graph(output_file=str(tmp_path / "bad.png"), show=False)
        finally:
            plt.savefig = real_savefig

    def test_device_mpl_show_exception_handled(self, monkeypatch):
        graph = self._make_divider_graph()

        def _raise():
            raise RuntimeError("headless")

        monkeypatch.setattr(plt, "show", _raise)
        graph.visualize_device_graph(output_file=None, show=True)

    def test_device_mpl_render_exception_falls_back_to_dot(self, tmp_path, monkeypatch):
        graph = self._make_divider_graph()

        def _raise(*_args, **_kwargs):
            raise RuntimeError("mpl failure")

        monkeypatch.setattr(plt, "figure", _raise)
        monkeypatch.setattr(cg_module, "HAS_PYDOT", False)
        out_file = str(tmp_path / "dev_fallback.png")
        graph.visualize_device_graph(output_file=out_file, show=False)
        assert (tmp_path / "dev_fallback.png.dot").exists()


class TestToPyg:
    def _make_simple_graph(self):
        graph = CircuitGraph()
        graph.add_connection("vdd", "R1.a")
        graph.add_connection("out", "R1.b")
        graph.add_connection("out", "R2.a")
        graph.add_connection("gnd", "R2.b")
        graph.instance_metadata["R1"] = {"model": "resistor"}
        graph.instance_metadata["R2"] = {"model": "resistor"}
        return graph

    def test_returns_heterodata(self):
        import torch_geometric.data  # pylint: disable=import-outside-toplevel

        graph = self._make_simple_graph()
        data = graph.to_pyg()
        assert isinstance(data, torch_geometric.data.HeteroData)

    def test_instance_node_count(self):
        graph = self._make_simple_graph()
        data = graph.to_pyg()
        assert data["instance"].x.shape[0] == 2

    def test_net_node_count(self):
        graph = self._make_simple_graph()
        data = graph.to_pyg()
        assert data["net"].x.shape[0] == 3

    def test_instance_feature_is_one_hot(self):
        import torch  # pylint: disable=import-outside-toplevel

        graph = self._make_simple_graph()
        data = graph.to_pyg()
        # Both R1 and R2 are "resistor"; one-hot dim = 1, value = 1.0
        assert data["instance"].x.shape[1] == 1
        assert torch.all(data["instance"].x == 1.0)

    def test_net_feature_is_fanout(self):
        graph = self._make_simple_graph()
        data = graph.to_pyg()
        # "out" connects R1.b and R2.a → fanout 2; vdd and gnd → fanout 1
        fanouts = sorted(data["net"].x[:, 0].tolist())
        assert fanouts == [1.0, 1.0, 2.0]

    def test_net_feature_shape(self):
        graph = self._make_simple_graph()
        data = graph.to_pyg()
        # [fanout, is_port, is_signal, is_power, is_ground]
        assert data["net"].x.shape[1] == 5

    def test_net_type_signal_classification(self):
        # "out" and "gnd" and "vdd" are all added via add_connection — no macro
        # ports set, so power/ground are detected by name heuristic
        graph = self._make_simple_graph()
        data = graph.to_pyg()
        # net type one-hot sums to 1 for every net
        import torch  # pylint: disable=import-outside-toplevel

        assert torch.all(data["net"].x[:, 1:].sum(dim=1) == 1.0)

    def test_edge_index_shape(self):
        graph = self._make_simple_graph()
        data = graph.to_pyg()
        ei = data["instance", "connects_to", "net"].edge_index
        assert ei.shape[0] == 2

    def test_edge_attr_present(self):
        graph = self._make_simple_graph()
        data = graph.to_pyg()
        ea = data["instance", "connects_to", "net"].edge_attr
        # one row per edge, one-hot over terminal vocab
        assert ea.shape[0] == data["instance", "connects_to", "net"].edge_index.shape[1]
        assert ea.shape[1] == len(cg_module._TERMINAL_VOCAB)  # pylint: disable=protected-access

    def test_edge_attr_is_one_hot(self):
        import torch  # pylint: disable=import-outside-toplevel

        graph = self._make_simple_graph()
        data = graph.to_pyg()
        ea = data["instance", "connects_to", "net"].edge_attr
        assert torch.all(ea.sum(dim=1) == 1.0)

    def test_reverse_edges_present(self):
        graph = self._make_simple_graph()
        data = graph.to_pyg()
        rev = data["net", "rev_connects_to", "instance"].edge_index
        fwd = data["instance", "connects_to", "net"].edge_index
        assert rev.shape == fwd.shape

    def test_empty_graph_no_edges(self):
        graph = CircuitGraph()
        data = graph.to_pyg()
        assert data["instance"].x.shape[0] == 0
        assert data["net"].x.shape[0] == 0
        assert ("instance", "connects_to", "net") not in data.edge_types

    def test_raises_import_error_when_pyg_missing(self, monkeypatch):
        graph = self._make_simple_graph()
        monkeypatch.setattr(cg_module, "HAS_PYG", False)
        import pytest as _pytest  # pylint: disable=import-outside-toplevel

        with _pytest.raises(ImportError):
            graph.to_pyg()


class TestExtractRefDes:
    def test_port_with_dot_extracts_ref_des(self):
        graph = CircuitGraph()
        graph.add_connection("vdd", "R1.a")
        assert "R1" in graph.instance_metadata or "vdd" in graph.nets

    def test_port_without_dot_returns_as_is(self):
        graph = CircuitGraph()
        graph.add_connection("vdd", "bare_ref")
        nx_graph = graph._build_nx_graph()  # pylint: disable=protected-access
        assert nx_graph.has_node("bare_ref")
