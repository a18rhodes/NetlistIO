# NetlistIO

A high-performance, parallel SPICE netlist parser and graph pipeline built for EDA tooling and machine learning workflows.

NetlistIO ingests arbitrarily large SPICE netlists — including deeply nested subcircuit hierarchies with `.lib` corner files — and produces a fully linked, hierarchical object model. From there, a bipartite net/instance graph can be exported as a PyTorch Geometric `HeteroData` object, ready for use in graph neural networks.

## Why

Existing SPICE parsers are either slow, single-threaded, incomplete in their handling of the `.lib`/`.include` include graph, or Python wrappers around C tools that are difficult to extend. NetlistIO is written from the ground up to be fast, correct, and structured around clean abstractions that make adding new format support (Verilog, SPEF) straightforward.

The end goal is a GNN-based circuit topology classifier trained on open-source analog and digital corpora (SKY130, OpenCores, AnalogGenie). NetlistIO is the data pipeline — the part every project like this needs but nobody publishes. See [Architecture](docs/architecture.md) for the full technical design and roadmap.

## Features

- **Parallel parsing**: Files are memory-mapped and split into independently parseable byte-range regions. A worker pool processes regions concurrently, then results are merged.
- **Recursive include resolution**: The compiler resolves `.include`, `.lib file section`, Cadence `[! ...]` / `[? ...]` directives iteratively, de-duplicating regions already visited.
- **Hierarchical linking**: Tree-shaking from top-level instances, topological sort of subcircuit definitions, cycle detection.
- **MOSFET type inference**: NMOS/PMOS classification from model name heuristics before `.model` linking.
- **Bipartite graph**: Net and instance nodes; port connections as edges. Connectivity analysis and Graphviz/matplotlib rendering included.
- **PyG export**: `to_pyg()` projects the graph to a `HeteroData` object with one-hot instance features and fanout net features.
- **Extensible**: `ScanStrategy`, `LineParser`, `ChunkParser`, `LibraryProcessor` are abstract base classes. Adding a new format is a matter of implementing those four interfaces.

## Installation

Requires Python 3.11.

```bash
pip install netlistio
```

With visualization support (Graphviz + matplotlib):

```bash
pip install "netlistio[viz]"
```

With PyTorch Geometric (CPU):

```bash
pip install netlistio
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install torch_geometric
```

For development:

```bash
git clone https://github.com/a18rhodes/NetlistIO
cd NetlistIO
poetry install
```

## Usage

### Python API

```python
from netlistio import SpiceReader

netlist = SpiceReader().read("path/to/top.sp")

# Iterate subcircuits
for name, subckt in netlist.macros.items():
    instances = list(subckt.instances)
    print(f"{name}: {len(instances)} instances")

# Build the bipartite graph and export to PyG
from netlistio.graph_analysis import CircuitGraph

cg = CircuitGraph.from_netlist(netlist)
data = cg.to_pyg()   # torch_geometric.data.HeteroData
```

### CLI

```bash
# Show scanner output — parse regions discovered in a file
netlistio regions top.sp

# Parse, link, and summarize
netlistio parse top.sp

# Full linked tree dump
netlistio dump top.sp

# Connectivity statistics for the bipartite graph
netlistio graph top.sp --stats

# Render the graph (requires viz extras)
netlistio graph top.sp --output topology.svg

# Scope to a specific subcircuit
netlistio graph top.sp --subckt my_ota --output ota.png

# Export a PyG HeteroData file
netlistio to-pyg top.sp output.pt
netlistio to-pyg top.sp output.pt --subckt my_ota
```

Use `-v` / `-vv` to raise log verbosity, `-q` to suppress warnings.

## Technical Design

See [docs/architecture.md](docs/architecture.md) for a detailed walkthrough of the parsing pipeline, include graph resolution, linking, bipartite graph construction, and the planned GNN classifier.

## Project Status

The core parser, linker, and graph builder are complete. Active work:

- `to_pyg()` implementation (complete, requires `torch_geometric`)
- Structural Verilog parser (planned)
- GNN classifier training pipeline (planned)

See [notes/plan.md](notes/plan.md) for the full roadmap.

## License

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
