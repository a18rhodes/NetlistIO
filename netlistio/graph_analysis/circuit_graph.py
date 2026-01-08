import networkx as nx
from typing import TYPE_CHECKING, Optional, Dict, List, Any, Set

try:
    from networkx.drawing.nx_pydot import to_pydot
    HAS_PYDOT = True
except ImportError:
    HAS_PYDOT = False
    to_pydot = None

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

if TYPE_CHECKING:
    from netlistio.models.generic import Netlist, Macro


class CircuitGraph:
    def __init__(self):
        self.nets: Dict[str, List[str]] = {}
        self.instance_metadata: Dict[str, Dict[str, str]] = {}

    @classmethod
    def from_netlist(cls, netlist: "Netlist") -> "CircuitGraph":
        return cls.from_macro(netlist.top)

    @classmethod
    def from_macro(cls, macro: "Macro") -> "CircuitGraph":
        graph = cls()
        graph._populate_from_macro(macro)
        return graph

    def _populate_from_macro(self, macro: "Macro") -> None:
        for instance in macro.children:
            self._process_instance_connections(instance)

    def _process_instance_connections(self, instance: Any) -> None:
        ref_des = instance.name

        # Capture metadata for visualization
        model_name = "Unknown"
        if instance.definition and instance.definition.name:
            model_name = instance.definition.name
        elif instance.definition_name:
            model_name = instance.definition_name

        self.instance_metadata[ref_des] = {"model": model_name}

        for net_name, formal_port in instance.nets.items():
            self._add_resolved_connection(net_name, ref_des, formal_port)

    def _add_resolved_connection(self, net_name: str, ref_des: str, formal_port: Any) -> None:
        identifier = self._format_port_identifier(ref_des, formal_port)
        self.add_connection(net_name, identifier)

    def _format_port_identifier(self, ref_des: str, formal_port: Any) -> str:
        if formal_port:
            return f"{ref_des}.{formal_port.name}"
        return ref_des

    def add_connection(self, net_name: str, port_name: str) -> None:
        self.nets.setdefault(net_name, []).append(port_name)

    def analyze_connectivity(self) -> None:
        self._print_header()
        if not self.nets:
            print("Graph is empty.")
            return
        graph = self._build_nx_graph()
        self._print_statistics(graph)

    def _print_header(self) -> None:
        print(f"--- Graph Statistics ---")
        print(f"Total Nets: {len(self.nets)}")

    def _print_statistics(self, graph: nx.Graph) -> None:
        degrees = self._get_net_degrees(graph)
        self._print_average_fanout(degrees)
        self._print_max_fanout(degrees)

    def _get_net_degrees(self, graph: nx.Graph) -> Dict[str, int]:
        nodes = [n for n, attr in graph.nodes(data=True) if attr.get("type") == "net"]
        return dict(graph.degree(nodes))

    def _print_average_fanout(self, degrees: Dict[str, int]) -> None:
        if not degrees:
            return
        avg = sum(degrees.values()) / len(degrees)
        print(f"Average Fanout: {avg:.2f}")

    def _print_max_fanout(self, degrees: Dict[str, int]) -> None:
        if not degrees:
            return
        max_net = max(degrees, key=degrees.get)
        count = degrees[max_net]
        print(f"Highest Fanout Net: {max_net} ({count} connections)")

    def visualize(self, output_file: Optional[str] = None, engine: str = "fdp", show: bool = True) -> None:
        graph = self._build_nx_graph()

        file_saved = False

        # 1. Pydot Strategy (File Saving Only)
        if output_file and HAS_PYDOT:
            if self._try_render_pydot(graph, output_file, engine):
                file_saved = True

        # 2. Matplotlib Strategy (Fallback Save + Interactive Show)
        should_save_mpl = (output_file is not None) and (not file_saved)
        should_show_mpl = show

        if should_save_mpl or should_show_mpl:
            target_file = output_file if should_save_mpl else None
            if self._try_render_matplotlib(graph, target_file, should_show_mpl):
                if target_file:
                    file_saved = True
            else:
                 if should_show_mpl:
                     print("Warning: Matplotlib interactive display failed or library missing.")

        # 3. Final Fallback (Raw DOT)
        if output_file and not file_saved:
             self._handle_visualization_failure(graph, output_file)
        elif show and not HAS_MATPLOTLIB and not output_file:
             print("Visualization Error: No display possible (Matplotlib missing) and no output file specified.")

    def _build_nx_graph(self) -> nx.Graph:
        graph = nx.Graph()
        self._populate_nx_graph(graph)
        return graph

    def _populate_nx_graph(self, graph: nx.Graph) -> None:
        processed_instances: Set[str] = set()
        for net_name, ports in self.nets.items():
            self._add_net_node(graph, net_name)
            self._process_ports_for_graph(graph, net_name, ports, processed_instances)

    def _add_net_node(self, graph: nx.Graph, net_name: str) -> None:
        graph.add_node(net_name, **self._get_net_attributes(net_name))

    def _get_net_attributes(self, net_name: str) -> Dict[str, str]:
        # Using 'xlabel' for external labels ensures the point remains small
        # but the text is placed nearby.
        return {
            "type": "net",
            "shape": "point",
            "width": "0.1",
            "color": "#5DADE2",
            "fixedsize": "true",
            "label": "",
            "xlabel": net_name,
            "fontsize": "10",      # Increased font size for visibility
            "fontcolor": "#2980B9" # Darker blue for contrast
        }

    def _process_ports_for_graph(self, graph: nx.Graph, net_name: str, ports: List[str], processed_instances: Set[str]) -> None:
        for port in ports:
            ref_des = self._extract_ref_des(port)
            self._ensure_instance_node(graph, ref_des, processed_instances)
            self._add_edge(graph, net_name, ref_des)

    def _extract_ref_des(self, port: str) -> str:
        if "." in port:
            return port.split(".")[0]
        return port

    def _ensure_instance_node(self, graph: nx.Graph, ref_des: str, processed_instances: Set[str]) -> None:
        if ref_des not in processed_instances:
            processed_instances.add(ref_des)
            graph.add_node(ref_des, **self._get_instance_attributes(ref_des))

    def _get_instance_attributes(self, ref_des: str) -> Dict[str, str]:
        model_name = self.instance_metadata.get(ref_des, {}).get("model", "")

        # Simplified label approach: standard string with newline.
        # Avoid HTML labels to prevent overflow/layout bugs in simple viewers.
        # "Mrecord" shape guarantees rounded corners.
        label_text = f"{ref_des}\\n({model_name})"

        return {
            "type": "instance",
            "shape": "Mrecord",    # Rounded record shape
            "style": "filled",     # Filled with color
            "fillcolor": "#34495E",
            "fontcolor": "white",
            "fontname": "Helvetica",
            "fontsize": "10",
            "margin": "0.1,0.05",
            "label": label_text,
            "mpl_label": f"{ref_des}\n({model_name})"
        }

    def _add_edge(self, graph: nx.Graph, source: str, target: str) -> None:
        graph.add_edge(source, target, color="#BDC3C7", penwidth="0.6")

    def _try_render_pydot(self, graph: nx.Graph, output_file: Optional[str], engine: str) -> bool:
        if not HAS_PYDOT:
            return False
        try:
            self._execute_pydot_render(graph, output_file, engine)
            return True
        except Exception as e:
            print(f"Graphviz rendering failed ({e}). Falling back...")
            return False

    def _execute_pydot_render(self, graph: nx.Graph, output_file: Optional[str], engine: str) -> None:
        if to_pydot is None:
            raise ImportError("networkx.drawing.nx_pydot failed to load")
        pydot_graph = to_pydot(graph)
        self._configure_pydot_graph(pydot_graph)

        if output_file:
            self._write_pydot_output(pydot_graph, output_file, engine)

    def _configure_pydot_graph(self, pydot_graph: Any) -> None:
        pydot_graph.set_overlap("false")
        pydot_graph.set_splines("true")
        pydot_graph.set("outputorder", "edgesfirst")
        # Global graph attributes to help compact the layout
        pydot_graph.set("nodesep", "0.6") # Minimum space between nodes
        pydot_graph.set("ranksep", "0.8") # Minimum space between ranks

    def _write_pydot_output(self, pydot_graph: Any, output_file: str, engine: str) -> None:
        ext = output_file.split(".")[-1].lower()
        if ext == "dot":
            pydot_graph.write_raw(output_file)
            print(f"Graph source saved to {output_file}")
            return
        self._write_formatted_pydot(pydot_graph, output_file, ext, engine)
        print(f"Graph visualization saved to {output_file} (using Graphviz)")

    def _write_formatted_pydot(self, pydot_graph: Any, output_file: str, ext: str, engine: str) -> None:
        write_method = f"write_{ext}"
        if hasattr(pydot_graph, write_method):
            getattr(pydot_graph, write_method)(output_file, prog=engine)
        else:
            pydot_graph.write(output_file, format=ext, prog=engine)

    def _try_render_matplotlib(self, graph: nx.Graph, output_file: Optional[str], show: bool) -> bool:
        if not HAS_MATPLOTLIB:
            return False
        try:
            self._execute_matplotlib_render(graph, output_file, show)
            return True
        except Exception as e:
            print(f"Matplotlib rendering failed: {e}")
            return False

    def _execute_matplotlib_render(self, graph: nx.Graph, output_file: Optional[str], show: bool) -> None:
        pos = nx.spring_layout(graph, k=0.6, iterations=50, seed=42)
        plt.figure(figsize=(12, 10))
        self._mpl_draw_components(graph, pos)
        self._mpl_finalize(output_file, show)

    def _mpl_draw_components(self, graph: nx.Graph, pos: Dict) -> None:
        self._mpl_draw_edges(graph, pos)
        self._mpl_draw_instances(graph, pos)
        self._mpl_draw_nets(graph, pos)
        self._mpl_draw_labels(graph, pos)

    def _mpl_draw_edges(self, graph: nx.Graph, pos: Dict) -> None:
        nx.draw_networkx_edges(graph, pos, edge_color="#BDC3C7", alpha=0.4, width=1.0)

    def _mpl_draw_instances(self, graph: nx.Graph, pos: Dict) -> None:
        nodes = [n for n, attr in graph.nodes(data=True) if attr.get("type") == "instance"]
        nx.draw_networkx_nodes(
            graph, pos, nodelist=nodes,
            node_color="#34495E", node_shape="s", node_size=1800, label="Instances", alpha=0.9
        )

    def _mpl_draw_nets(self, graph: nx.Graph, pos: Dict) -> None:
        nodes = [n for n, attr in graph.nodes(data=True) if attr.get("type") == "net"]
        nx.draw_networkx_nodes(
            graph, pos, nodelist=nodes,
            node_color="#5DADE2", node_shape="o", node_size=100, label="Nets", alpha=0.8
        )

    def _mpl_draw_labels(self, graph: nx.Graph, pos: Dict) -> None:
        # Draw instance labels (white on dark)
        inst_nodes = [n for n, attr in graph.nodes(data=True) if attr.get("type") == "instance"]
        inst_labels = {n: (attr.get("mpl_label") or n) for n, attr in graph.nodes(data=True) if attr.get("type") == "instance"}

        nx.draw_networkx_labels(graph, pos, labels=inst_labels, font_size=9, font_color="white", font_weight="bold")

        # Draw net labels
        net_labels = {n: (attr.get("xlabel") or n) for n, attr in graph.nodes(data=True) if attr.get("type") == "net"}
        nx.draw_networkx_labels(graph, pos, labels=net_labels, font_size=8, font_color="#5DADE2")

    def _mpl_finalize(self, output_file: Optional[str], show: bool) -> None:
        plt.title("Netlist Topology (Matplotlib Fallback)", fontsize=14, color="#2C3E50")
        plt.axis("off")
        if output_file:
            self._mpl_save(output_file)
        if show:
            self._mpl_show()
        plt.close()

    def _mpl_save(self, output_file: str) -> None:
        try:
            plt.savefig(output_file, dpi=150, bbox_inches='tight')
            print(f"Graph saved to {output_file} (using Matplotlib)")
        except Exception as e:
            print(f"Failed to save graph: {e}")

    def _mpl_show(self) -> None:
        try:
            plt.show()
        except Exception:
            print("Unable to display plot interactively (headless environment).")

    def _handle_visualization_failure(self, graph: nx.Graph, output_file: str) -> None:
        print("Error: Visualization libraries missing or failed.")
        dot_file = output_file + ".dot" if not output_file.endswith(".dot") else output_file
        print(f"Saving raw DOT content to '{dot_file}' instead.")
        self._save_fallback_dot(graph, dot_file)

    def _save_fallback_dot(self, graph: nx.Graph, filepath: str) -> None:
        try:
            with open(filepath, "w") as f:
                self._write_dot_content(f, graph)
            print(f"Fallback successful: Saved DOT source to {filepath}")
        except Exception as e:
            print(f"Critical Error: Could not save fallback file. {e}")

    def _write_dot_content(self, f: Any, graph: nx.Graph) -> None:
        f.write("graph Circuit {\n")
        f.write('  overlap="false";\n')
        f.write('  splines="true";\n')
        self._write_dot_nodes(f, graph)
        self._write_dot_edges(f, graph)
        f.write("}\n")

    def _write_dot_nodes(self, f: Any, graph: nx.Graph) -> None:
        for node, attrs in graph.nodes(data=True):
            attr_str = self._format_dot_attrs(attrs)
            f.write(f'  "{node}" [{attr_str}];\n')

    def _write_dot_edges(self, f: Any, graph: nx.Graph) -> None:
        for u, v, attrs in graph.edges(data=True):
            attr_str = self._format_dot_attrs(attrs)
            f.write(f'  "{u}" -- "{v}" [{attr_str}];\n')

    def _format_dot_attrs(self, attrs: Dict[str, Any]) -> str:
        return ", ".join([f'{k}="{v}"' for k, v in attrs.items()])
