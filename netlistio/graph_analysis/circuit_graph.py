"""
Bipartite net/instance graph builder with visualization and PyG projection.

Builds a flat bipartite graph where every node is either a net or a device
instance and every edge represents a port connection. Supports connectivity
analysis, matplotlib rendering, DOT export, and projection to a PyTorch
Geometric HeteroData object for downstream GNN workflows.
"""

# Rendering is best-effort: any backend failure must degrade gracefully, never
# crash analysis, so broad catches are intentional here.
# pylint: disable=broad-exception-caught

import logging
from typing import TYPE_CHECKING, Any

import networkx as nx

from netlistio.models.generic import Primitive
from netlistio.models.spice import prefix_registry

_LOGGER = logging.getLogger(__name__)

__all__ = ["CircuitGraph"]

# Terminal vocabulary derived from all known primitive port names.
# Order is stable (dict.fromkeys preserves insertion order across registered
# primitives) and automatically expands when new primitives are added.
_TERMINAL_VOCAB: tuple[str, ...] = tuple(
    dict.fromkeys(
        p.name
        for cls in prefix_registry().values()
        if issubclass(cls, Primitive) and isinstance(getattr(cls, "ports", None), tuple)
        for p in cls.ports
    )
) + ("other",)
_TERMINAL_IDX: dict[str, int] = {t: i for i, t in enumerate(_TERMINAL_VOCAB)}

_GROUND_NAMES: frozenset[str] = frozenset({"0", "gnd", "vss", "gnd!", "agnd", "avss", "dgnd", "pgnd", "vgnd"})
_POWER_PREFIXES: tuple[str, ...] = ("vdd", "vcc", "vdda", "vddio", "avdd", "dvdd", "pvdd", "vddh")
_NET_TYPE_NAMES: tuple[str, ...] = ("port", "signal", "power", "ground")
_NET_TYPE_IDX: dict[str, int] = {t: i for i, t in enumerate(_NET_TYPE_NAMES)}

try:
    from networkx.drawing.nx_pydot import to_pydot

    HAS_PYDOT = True
except ImportError:  # pragma: no cover
    HAS_PYDOT = False
    to_pydot = None

try:
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ImportError:  # pragma: no cover
    HAS_MATPLOTLIB = False

try:
    import torch
    from torch_geometric.data import HeteroData

    HAS_PYG = True
except ImportError:  # pragma: no cover
    HAS_PYG = False

if TYPE_CHECKING:
    from netlistio.models.generic import Macro, Netlist


class CircuitGraph:
    """
    Net/instance connectivity view of a netlist scope.

    Internally stores a net-centric adjacency table (``self.nets``) from which
    two graph projections are derived on demand:

    - **Bipartite** (``_build_nx_graph``): net nodes + instance nodes, one edge
      per port connection. Used by visualization backends and ``to_pyg()``.
    - **Device** (``to_device_graph``): instance-only nodes, edges when two
      instances share a net, weight = number of shared nets. The natural EE
      representation for connectivity analysis and path finding.

    Rendering uses matplotlib exclusively. pydot is retained for ``.dot`` file
    export only (and only when available); it is not involved in image rendering.
    """

    def __init__(self):
        self.nets: dict[str, list[str]] = {}
        self.instance_metadata: dict[str, dict[str, str]] = {}
        self._port_nets: frozenset[str] = frozenset()

    @classmethod
    def from_netlist(cls, netlist: "Netlist") -> "CircuitGraph":
        """
        Builds a graph from a netlist's virtual top-level scope.

        :param netlist: The netlist whose top scope is graphed.
        :return: Populated CircuitGraph.
        """
        return cls.from_macro(netlist.top)

    @classmethod
    def from_macro(cls, macro: "Macro") -> "CircuitGraph":
        """
        Builds a graph from the instances within a single macro scope.

        :param macro: The macro whose instances are graphed.
        :return: Populated CircuitGraph.
        """
        graph = cls()
        graph._port_nets = frozenset(p.name for p in macro.ports)
        graph._populate_from_macro(macro)
        return graph

    def _populate_from_macro(self, macro: "Macro") -> None:
        """Iterates macro instances and records their net connections."""
        for instance in macro.instances:
            self._process_instance_connections(instance)

    def _process_instance_connections(self, instance: Any) -> None:
        """Extracts model name and net connections from a single instance."""
        ref_des = instance.name
        model_name = "Unknown"
        if instance.definition and instance.definition.name:
            model_name = instance.definition.name
        elif instance.definition_name:
            model_name = instance.definition_name
        self.instance_metadata[ref_des] = {"model": model_name}
        for net_name, formal_port in instance.nets:
            self._add_resolved_connection(net_name, ref_des, formal_port)

    def _add_resolved_connection(self, net_name: str, ref_des: str, formal_port: Any) -> None:
        """Records a net-to-port-identifier connection."""
        self.add_connection(net_name, self._format_port_identifier(ref_des, formal_port))

    def _format_port_identifier(self, ref_des: str, formal_port: Any) -> str:
        """Returns ``ref_des.port`` when the port is resolved, else just ``ref_des``."""
        if formal_port:
            return f"{ref_des}.{formal_port.name}"
        return ref_des

    def add_connection(self, net_name: str, port_name: str) -> None:
        """
        Records a connection between a net and a port identifier.

        :param net_name: The net the port attaches to.
        :param port_name: Port identifier, formatted as ``ref_des`` or ``ref_des.port``.
        """
        self.nets.setdefault(net_name, []).append(port_name)

    def analyze_connectivity(self) -> None:
        """Prints net fan-out statistics for the bipartite graph to stdout."""
        print("--- Graph Statistics ---")
        print(f"Total Nets: {len(self.nets)}")
        if not self.nets:
            print("Graph is empty.")
            return
        graph = self._build_nx_graph()
        net_nodes = [n for n, attr in graph.nodes(data=True) if attr.get("type") == "net"]
        degrees = dict(graph.degree(net_nodes))
        if degrees:
            avg = sum(degrees.values()) / len(degrees)
            max_net = max(degrees, key=degrees.get)
            print(f"Average Fanout: {avg:.2f}")
            print(f"Highest Fanout Net: {max_net} ({degrees[max_net]} connections)")

    def to_device_graph(self) -> nx.Graph:
        """
        Projects the bipartite graph onto device (instance) nodes only.

        Two instances share an edge when they are both connected to the same
        net. The ``shared_nets`` edge attribute records how many nets are in
        common; ``nets`` carries the list of those net names.

        This is the EE-natural representation: it answers "which devices are
        electrically adjacent?" without the GNN overhead of explicit net nodes.

        :return: Undirected weighted NetworkX graph over instance nodes.
        """
        graph = nx.Graph()
        for name, meta in self.instance_metadata.items():
            graph.add_node(name, model=meta["model"])
        for net_name, ports in self.nets.items():
            ref_des_list = [p.split(".")[0] if "." in p else p for p in ports]
            for i, a in enumerate(ref_des_list):
                for b in ref_des_list[i + 1 :]:
                    if a == b:
                        continue
                    if graph.has_edge(a, b):
                        graph[a][b]["shared_nets"] += 1
                        graph[a][b]["nets"].append(net_name)
                    else:
                        graph.add_edge(a, b, shared_nets=1, nets=[net_name])
        return graph

    def analyze_device_connectivity(self) -> None:
        """
        Prints degree statistics for the device-projection graph to stdout.

        Degree here means the number of *distinct device neighbors* (not nets),
        which is the EE-meaningful connectivity metric: how many other devices
        does each instance directly share a net with?
        """
        print("--- Device Graph Statistics ---")
        print(f"Total Instances: {len(self.instance_metadata)}")
        if not self.instance_metadata:
            print("Graph is empty.")
            return
        graph = self.to_device_graph()
        degrees = dict(graph.degree())
        avg = sum(degrees.values()) / len(degrees)
        max_inst = max(degrees, key=degrees.get)
        print(f"Average Device Degree: {avg:.2f}")
        print(f"Most Connected Device: {max_inst} ({degrees[max_inst]} neighbors)")
        isolated = [n for n, d in degrees.items() if d == 0]
        if isolated:
            print(f"Isolated Instances ({len(isolated)}): {', '.join(isolated)}")

    def _classify_net_type(self, net_name: str) -> str:
        """
        Classifies a net as 'port', 'signal', 'power', or 'ground'.

        Port classification takes priority; power/ground are detected by name
        convention; everything else is a signal.

        :param net_name: Net identifier string.
        :return: One of 'port', 'signal', 'power', 'ground'.
        """
        if net_name in self._port_nets:
            return "port"
        nl = net_name.lower()
        if nl in _GROUND_NAMES or nl.startswith("vss") or nl.startswith("gnd"):
            return "ground"
        if any(nl.startswith(p) for p in _POWER_PREFIXES):
            return "power"
        return "signal"

    def _build_instance_features(self, inst_idx: dict) -> "torch.Tensor":
        """Builds one-hot instance feature matrix keyed by model name."""
        model_vocab = sorted({meta["model"] for meta in self.instance_metadata.values()})
        model_idx = {m: i for i, m in enumerate(model_vocab)}
        inst_x = torch.zeros(len(inst_idx), max(len(model_vocab), 1))
        for name, meta in self.instance_metadata.items():
            inst_x[inst_idx[name], model_idx[meta["model"]]] = 1.0
        return inst_x

    def _build_net_features(self, net_idx: dict) -> "torch.Tensor":
        """Builds net feature matrix: [fanout, is_port, is_signal, is_power, is_ground]."""
        net_x = torch.zeros(len(net_idx), 1 + len(_NET_TYPE_NAMES))
        for name, ports in self.nets.items():
            i = net_idx[name]
            net_x[i, 0] = float(len(ports))
            net_x[i, 1 + _NET_TYPE_IDX[self._classify_net_type(name)]] = 1.0
        return net_x

    def _build_edge_tensors(self, inst_idx: dict, net_idx: dict) -> "tuple[list, list, list]":
        """Builds src/dst index lists and one-hot terminal edge feature rows."""
        src_inst, dst_net, edge_feats = [], [], []
        n_terms = len(_TERMINAL_VOCAB)
        for net_name, ports in self.nets.items():
            n_i = net_idx[net_name]
            for port in ports:
                parts = port.split(".")
                ref_des = parts[0]
                terminal = parts[1] if len(parts) > 1 else "other"
                if ref_des in inst_idx:
                    src_inst.append(inst_idx[ref_des])
                    dst_net.append(n_i)
                    feat = [0.0] * n_terms
                    feat[_TERMINAL_IDX.get(terminal, _TERMINAL_IDX["other"])] = 1.0
                    edge_feats.append(feat)
        return src_inst, dst_net, edge_feats

    def to_pyg(self) -> "HeteroData":
        """
        Projects the bipartite graph to a PyTorch Geometric HeteroData object.

        Node types: ``instance`` and ``net``.
        Edge types: ``instance -> connects_to -> net`` and its reverse.

        Instance node features: one-hot over model name vocabulary.
        Net node features: ``[fanout, is_port, is_signal, is_power, is_ground]``.
        Edge features: one-hot over terminal name vocabulary (d/g/s/b/a/k/other),
        derived from the formal port resolved by the linker.

        Terminal vocabulary is derived from all registered primitive port names
        (see ``_TERMINAL_VOCAB``); 'other' covers unresolved subcircuit ports.

        :return: HeteroData with node features, edge indices, and edge attributes.
        :raises ImportError: If torch or torch_geometric are not installed.
        """
        if not HAS_PYG:
            raise ImportError(
                "torch and torch_geometric are required for to_pyg(). "
                "Install via: pip install torch --index-url https://download.pytorch.org/whl/cpu "
                "&& pip install torch_geometric"
            )
        inst_idx = {name: i for i, name in enumerate(sorted(self.instance_metadata))}
        net_idx = {name: i for i, name in enumerate(sorted(self.nets))}
        src_inst, dst_net, edge_feats = self._build_edge_tensors(inst_idx, net_idx)
        data = HeteroData()
        data["instance"].x = self._build_instance_features(inst_idx)
        data["net"].x = self._build_net_features(net_idx)
        if src_inst:
            edge_index = torch.tensor([src_inst, dst_net], dtype=torch.long)
            edge_attr = torch.tensor(edge_feats, dtype=torch.float)
            data["instance", "connects_to", "net"].edge_index = edge_index
            data["instance", "connects_to", "net"].edge_attr = edge_attr
            data["net", "rev_connects_to", "instance"].edge_index = edge_index.flip(0)
            data["net", "rev_connects_to", "instance"].edge_attr = edge_attr
        return data

    def visualize(  # pylint: disable=unused-argument
        self, output_file: str | None = None, engine: str = "fdp", show: bool = True
    ) -> None:
        """
        Renders the bipartite graph using matplotlib, or exports DOT source.

        When ``output_file`` ends with ``.dot``, raw DOT source is written
        (pydot used when available, plain writer otherwise). All other
        extensions (``svg``, ``png``, ``pdf``, etc.) are rendered via
        matplotlib, which handles the layout and format natively.

        :param output_file: Destination path; extension selects the format.
        :param engine: Unused for image output; kept for API stability.
        :param show: Whether to display the graph interactively.
        """
        graph = self._build_nx_graph()
        if output_file and output_file.endswith(".dot"):
            self._export_dot(graph, output_file)
            return
        rendered = self._try_render_matplotlib(graph, output_file, show)
        if not rendered and output_file:
            dot_path = output_file + ".dot"
            _LOGGER.warning("Matplotlib unavailable. Saving DOT fallback to '%s'.", dot_path)
            self._export_dot(graph, dot_path)
        elif not rendered and show:
            _LOGGER.warning("No display possible: Matplotlib missing and no output file specified.")

    def visualize_device_graph(  # pylint: disable=unused-argument
        self, output_file: str | None = None, engine: str = "fdp", show: bool = True
    ) -> None:
        """
        Renders the device-projection graph using matplotlib, or exports DOT source.

        Nodes are instances; edges represent shared net connections with edge
        width proportional to the number of shared nets.

        :param output_file: Destination path; extension selects the format.
        :param engine: Unused for image output; kept for API stability.
        :param show: Whether to display interactively.
        """
        dg = self._build_device_nx_graph()
        if output_file and output_file.endswith(".dot"):
            self._export_dot(dg, output_file)
            return
        rendered = self._try_render_matplotlib_device(dg, output_file, show)
        if not rendered and output_file:
            dot_path = output_file + ".dot"
            _LOGGER.warning("Matplotlib unavailable. Saving DOT fallback to '%s'.", dot_path)
            self._export_dot(dg, dot_path)
        elif not rendered and show:
            _LOGGER.warning("No display possible: Matplotlib missing and no output file specified.")

    def _export_dot(self, graph: nx.Graph, output_file: str) -> None:
        """
        Writes DOT source for *graph* to *output_file*.

        Uses pydot when available for richer attribute serialisation; falls back
        to the hand-written writer otherwise.

        :param graph: NetworkX graph to serialise.
        :param output_file: Destination path (should end with ``.dot``).
        """
        if HAS_PYDOT and to_pydot is not None:
            try:
                to_pydot(graph).write_raw(output_file)  # type: ignore[attr-defined]  # pylint: disable=no-member
                _LOGGER.info("DOT source saved to %s (pydot)", output_file)
                return
            except Exception as e:
                _LOGGER.warning("pydot DOT export failed (%s), using fallback writer.", e)
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                self._write_dot_content(f, graph)
            _LOGGER.info("DOT source saved to %s", output_file)
        except Exception as e:
            _LOGGER.error("Could not write DOT file: %s", e)

    def _build_nx_graph(self) -> nx.Graph:
        """Constructs and returns the NetworkX bipartite graph."""
        graph = nx.Graph()
        self._populate_nx_graph(graph)
        return graph

    def _populate_nx_graph(self, graph: nx.Graph) -> None:
        """Adds net and instance nodes with their edges to *graph*."""
        processed_instances: set[str] = set()
        for net_name, ports in self.nets.items():
            graph.add_node(net_name, **self._get_net_attributes(net_name))
            self._process_ports_for_graph(graph, net_name, ports, processed_instances)

    def _process_ports_for_graph(
        self, graph: nx.Graph, net_name: str, ports: list[str], processed_instances: set[str]
    ) -> None:
        """Ensures instance nodes exist and adds edges for each port on *net_name*."""
        for port in ports:
            ref_des = port.split(".")[0] if "." in port else port
            if ref_des not in processed_instances:
                processed_instances.add(ref_des)
                graph.add_node(ref_des, **self._get_instance_attributes(ref_des))
            graph.add_edge(net_name, ref_des, color="#BDC3C7", penwidth="0.6")

    def _get_net_attributes(self, net_name: str) -> dict[str, str]:
        """Returns node attributes for a net node."""
        return {
            "type": "net",
            # circle + fixedsize keeps the node compact while remaining visible;
            # xlabel floats the label outside the circle boundary in Graphviz.
            "shape": "circle",
            "width": "0.35",
            "fixedsize": "true",
            "style": "filled",
            "fillcolor": "#AED6F1",
            "color": "#2980B9",
            "label": "",
            "xlabel": net_name,
            "fontsize": "9",
            "fontcolor": "#1A5276",
        }

    def _get_instance_attributes(self, ref_des: str) -> dict[str, str]:
        """Returns node attributes for an instance node."""
        model_name = self.instance_metadata.get(ref_des, {}).get("model", "")
        return {
            "type": "instance",
            # Mrecord produces rounded corners; plain record does not.
            "shape": "Mrecord",
            "style": "filled",
            "fillcolor": "#34495E",
            "fontcolor": "white",
            "fontname": "Helvetica",
            "fontsize": "9",
            "width": "1.0",
            "height": "0.5",
            "margin": "0.08,0.04",
            "label": f"{ref_des}\\n({model_name})",
            "mpl_label": f"{ref_des}\n({model_name})",
        }

    def _build_device_nx_graph(self) -> nx.Graph:
        """Builds a styled NetworkX graph from the device projection."""
        dg = self.to_device_graph()
        for node in dg.nodes:
            dg.nodes[node].update(self._get_instance_attributes(node))
        for *_, data in dg.edges(data=True):
            nets = data.get("nets", [])
            label = ", ".join(nets[:2]) + ("..." if len(nets) > 2 else "")
            data.update(
                {
                    "color": "#5D6D7E",
                    "penwidth": str(min(data.get("shared_nets", 1), 5)),
                    "label": label,
                    "fontsize": "8",
                }
            )
        return dg

    def _device_edge_labels(self, graph: nx.Graph) -> dict[tuple, str]:
        """Returns matplotlib edge label strings for the device graph."""
        labels = {}
        for u, v, data in graph.edges(data=True):
            nets = data.get("nets", [])
            if len(nets) <= 2:
                labels[(u, v)] = "\n".join(nets)
            else:
                labels[(u, v)] = "\n".join(nets[:2]) + f"\n+{len(nets) - 2} more"
        return labels

    def _try_render_matplotlib(self, graph: nx.Graph, output_file: str | None, show: bool) -> bool:
        """Attempts a matplotlib render of the bipartite graph. Returns True on success."""
        if not HAS_MATPLOTLIB:
            return False
        try:
            self._execute_matplotlib_render(graph, output_file, show)
            return True
        except Exception as e:
            _LOGGER.warning("Matplotlib rendering failed: %s", e)
            return False

    def _execute_matplotlib_render(self, graph: nx.Graph, output_file: str | None, show: bool) -> None:
        """Lays out and draws the bipartite graph with matplotlib."""
        net_nodes = [n for n, attr in graph.nodes(data=True) if attr.get("type") == "net"]
        # bipartite_layout puts net nodes on the left column, instance nodes on
        # the right, which reflects the actual two-set structure of the graph.
        pos = nx.bipartite_layout(graph, nodes=net_nodes, align="vertical", scale=2)
        plt.figure(figsize=(12, 10))
        self._mpl_draw_edges(graph, pos)
        self._mpl_draw_instances(graph, pos)
        self._mpl_draw_nets(graph, pos)
        self._mpl_draw_labels(graph, pos)
        plt.title("Netlist Topology", fontsize=14, color="#2C3E50")
        plt.axis("off")
        if output_file:
            try:
                plt.savefig(output_file, dpi=150, bbox_inches="tight")
                _LOGGER.info("Graph saved to %s", output_file)
            except Exception as e:
                _LOGGER.warning("Failed to save graph: %s", e)
        if show:
            try:
                plt.show()
            except Exception:
                _LOGGER.warning("Unable to display plot interactively (headless environment).")
        plt.close()

    def _mpl_draw_edges(self, graph: nx.Graph, pos: dict) -> None:
        """Draws all edges with a neutral style."""
        nx.draw_networkx_edges(graph, pos, edge_color="#BDC3C7", alpha=0.4, width=1.0)

    def _mpl_draw_instances(self, graph: nx.Graph, pos: dict) -> None:
        """Draws instance nodes as filled squares."""
        nodes = [n for n, attr in graph.nodes(data=True) if attr.get("type") == "instance"]
        nx.draw_networkx_nodes(
            graph,
            pos,
            nodelist=nodes,
            node_color="#34495E",
            node_shape="s",
            node_size=900,
            label="Instances",
            alpha=0.9,
        )

    def _mpl_draw_nets(self, graph: nx.Graph, pos: dict) -> None:
        """Draws net nodes as circles proportional to instance nodes."""
        nodes = [n for n, attr in graph.nodes(data=True) if attr.get("type") == "net"]
        nx.draw_networkx_nodes(
            graph, pos, nodelist=nodes, node_color="#AED6F1", node_shape="o", node_size=350, label="Nets", alpha=0.9
        )

    def _mpl_draw_labels(self, graph: nx.Graph, pos: dict) -> None:
        """Draws instance and net labels in their respective styles."""
        inst_labels = {
            n: (attr.get("mpl_label") or n) for n, attr in graph.nodes(data=True) if attr.get("type") == "instance"
        }
        nx.draw_networkx_labels(graph, pos, labels=inst_labels, font_size=9, font_color="white", font_weight="bold")
        net_labels = {n: (attr.get("xlabel") or n) for n, attr in graph.nodes(data=True) if attr.get("type") == "net"}
        nx.draw_networkx_labels(graph, pos, labels=net_labels, font_size=8, font_color="#5DADE2")

    def _try_render_matplotlib_device(self, graph: nx.Graph, output_file: str | None, show: bool) -> bool:
        """Attempts a matplotlib render of the device graph. Returns True on success."""
        if not HAS_MATPLOTLIB:
            return False
        try:
            pos = nx.spring_layout(graph, k=1.5, iterations=100, seed=42)
            plt.figure(figsize=(12, 10))
            weights = [max(1, graph[u][v].get("shared_nets", 1)) for u, v in graph.edges()]
            nx.draw_networkx_edges(graph, pos, width=weights, edge_color="#5D6D7E", alpha=0.6)
            nx.draw_networkx_nodes(graph, pos, node_color="#34495E", node_shape="s", node_size=900, alpha=0.9)
            inst_labels = {n: f"{n}\n({graph.nodes[n].get('model', '')})" for n in graph.nodes}
            nx.draw_networkx_labels(graph, pos, labels=inst_labels, font_size=8, font_color="white")
            nx.draw_networkx_edge_labels(
                graph, pos, edge_labels=self._device_edge_labels(graph), font_size=7, font_color="#1A252F"
            )
            plt.title("Device Connectivity Graph", fontsize=14, color="#2C3E50")
            plt.axis("off")
            if output_file:
                try:
                    plt.savefig(output_file, dpi=150, bbox_inches="tight")
                    _LOGGER.info("Device graph saved to %s", output_file)
                except Exception as e:
                    _LOGGER.warning("Failed to save device graph: %s", e)
            if show:
                try:
                    plt.show()
                except Exception:
                    _LOGGER.warning("Unable to display plot interactively (headless environment).")
            plt.close()
            return True
        except Exception as e:
            _LOGGER.warning("Matplotlib device graph rendering failed: %s", e)
            return False

    def _write_dot_content(self, f: Any, graph: nx.Graph) -> None:
        """Writes a minimal DOT representation of *graph* to file *f*."""
        f.write("graph Circuit {\n")
        f.write('  overlap="false";\n')
        f.write('  splines="true";\n')
        for node, attrs in graph.nodes(data=True):
            f.write(f'  "{node}" [{self._format_dot_attrs(attrs)}];\n')
        for u, v, attrs in graph.edges(data=True):
            f.write(f'  "{u}" -- "{v}" [{self._format_dot_attrs(attrs)}];\n')
        f.write("}\n")

    def _format_dot_attrs(self, attrs: dict[str, Any]) -> str:
        """Serialises a node/edge attribute dict to a DOT attribute string."""
        return ", ".join(f'{k}="{self._escape_dot(v)}"' for k, v in attrs.items())

    @staticmethod
    def _escape_dot(value: Any) -> str:
        """Escapes embedded quotes so a value cannot break out of a DOT string."""
        return str(value).replace('"', '\\"')
