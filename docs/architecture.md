# NetlistIO Architecture

## Overview

NetlistIO is structured as a five-stage pipeline:

```
File(s)
  └─ Scanner        — byte-range region discovery (mmap, per-file)
       └─ Compiler  — recursive include graph resolution
            └─ Parser     — parallel chunk parsing (worker pool)
                 └─ Linker      — model resolution, tree-shaking, topo sort
                      └─ CircuitGraph  — bipartite graph + PyG projection
```

Each stage takes a defined input type and produces a defined output type. No stage holds a reference to any stage above it.

---

## Stage 1: Memory Mapping and Scanning

Files are opened with `mmap(ACCESS_READ)`. The reason is lazy page loading: the OS maps the file into the process address space without reading it, and faults in only the pages that are accessed. On netlists that run into the hundreds of gigabytes, this keeps physical memory use proportional to what is actually parsed rather than to file size. A `read()`-based approach that loads the file upfront does not have this property.

For the sequential scanning phase, buffered `read()` and mmap are roughly equivalent — kernel read-ahead covers most of the page fault latency, and the scanner reads end-to-end regardless. For the worker dispatch phase, each worker opens its own mmap handle independently, seeks once to `start_byte`, and reads sequentially within its region. The access pattern per worker is sequential after that seek, so per-worker mmap handles and buffered file handles behave similarly for throughput. Workers do not share a single mapping; physical pages are shared only via the OS page cache, which both approaches benefit from equally.

A pre-fork shared mapping — opening one mmap before spawning the pool, then accessing worker regions via `memoryview` slices — would eliminate per-worker file opens and avoid the encode/decode round-trips that str-based line processing introduces. On Linux with the `fork` start method this works cleanly. The problem is that `fork` is being phased out as the default: macOS and Windows have always defaulted to `spawn`, and CPython is moving Linux the same way. The spawn-safe alternative, `multiprocessing.shared_memory`, requires loading the full file into RAM upfront, which is not viable for netlists that reach into the hundreds of gigabytes. The per-worker mmap approach is the pragmatic choice until there is a better story for large-file shared memory under spawn.

The `Scanner` runs a finite state machine over the mmap'd file, reading one line at a time to detect SUBCKT/ENDS boundaries. For each `.SUBCKT`/`.ENDS` pair it emits a `ParseRegion(start_byte, end_byte, MACRO)`. The interstitial content between subcircuits is emitted as `ParseRegion(..., GLOBAL)`. No text is decoded or stored at this stage; only byte offsets.

The `ScanStrategy` interface abstracts the format-specific detection logic. `SpiceScanStrategy` implements `.SUBCKT` / `.ENDS` detection via compiled byte regexes. A Verilog implementation would detect `module`/`endmodule` boundaries.

---

## Stage 2: Compiler: Recursive Include Resolution

SPICE netlists are rarely a single file. `.include path` and `.lib path section` directives pull in corner files, technology libraries, and design units. NetlistIO resolves the full include graph iteratively, not recursively, to avoid stack depth limits on deep hierarchies.

The `Compiler` maintains a work queue of `ParseRegion` objects. It starts with a single "whole file" region for the root file. As each region is parsed, any `.include`/`.lib` directives it emits are resolved to absolute paths and enqueued as new regions. Already-visited `(filepath, start_byte, end_byte)` triples are deduplicated, preventing infinite loops on circular includes.

`.lib file section` directives cause the `LibraryProcessor` to scan the target file for the section's byte boundaries and enqueue only that byte slice. For example, `tt.lib` typically contains multiple sections (`tt`, `ff`, `ss`); a `.lib tt.lib tt` directive enqueues only the `tt` section's byte range, skipping the rest of the file.

---

## Stage 3: Parallel Chunk Parsing

Each `ParseRegion` becomes one unit of work. A `multiprocessing.Pool` distributes regions across worker processes. Workers independently open their own mmap handles to the file (mmap is not shared across processes), seek to `start_byte`, and parse until `end_byte`.

The `ChunkParser` owns the physical-to-logical line assembly logic. In SPICE, a logical line may span multiple physical lines joined by `+` continuation characters. `SpiceChunkParser` accumulates physical lines into logical lines, then delegates each logical line to `SpiceLineParser`.

`SpiceLineParser` implements three dispatch methods:

- `parse_instance(line)` — identifies device instances by their SPICE prefix character (`R`, `C`, `L`, `M`, `X`, `D`). Extracts net connections as an ordered `list[NetConnection]` and `key=value` parameters. For passives, handles the trailing bare value convention (`R1 net_a net_b 10k`). For MOSFETs, applies a heuristic to pre-classify NMOS/PMOS from the model name before linking. Duplicate net names in a single instance line are preserved as separate entries so that tied terminals (e.g. `vss vss` for source and bulk) receive correct positional port assignments during linking.
- `parse_declaration(line)` — handles `.SUBCKT` (emits a `Subckt` model) and `.MODEL` (emits a `Model`).
- `parse_include(line)` — handles `.include`, `.lib`, and Cadence `[! ...]` / `[? ...]` include variants.

Worker results (`ParseResult` objects) are merged on the coordinator side: cells and errors are concatenated, includes are deduplicated.

---

## Stage 4: Linking

The `link()` function takes the flat list of parsed cells and resolves instance references to definitions.

### Net connection representation

`Instance.nets` is a `list[NetConnection]`, where each `NetConnection(net, port)` records one terminal connection in positional order. `NetConnection` supports tuple unpacking (`net, port = conn`) via `__iter__`. Before linking, `port` is `None`; after linking it holds the `Port` object from the definition.

Using a list rather than a dict allows the same net name to appear at multiple positions, which is necessary for devices with tied terminals (e.g. a MOSFET where source and bulk both connect to `vss`).

### Tree-shaking

Starting from top-level instances (instances that appear outside any subcircuit definition), the linker traverses the hierarchy with a BFS queue. Only definitions reachable from the traversal are included in the output netlist. For library-only files (no top-level instances), all parsed macros are seeded into the traversal to prevent silent omission.

### Formal port mapping

When an instance is linked to its definition, the linker maps the ordered net names from the instance line to the ordered formal port names from the definition, positionally:

- **Macro instances**: ports come from the `.SUBCKT` declaration. `_handle_macro` zips `instance.nets` with `macro.ports` and writes the resolved `Port` objects back.
- **Primitive instances**: ports come from the class-level `Primitive.ports` tuple (e.g. `(Port("d"), Port("g"), Port("s"), Port("b"))` for MOSFETs). `_assign_primitive_ports` performs the same positional zip. This is where MOSFET gate/drain/source/bulk roles are stamped onto each `NetConnection`.

A warning is logged when the connection count does not match the port count; the instance retains `None` port values in that case.

### Topological sort

Macros are sorted by dependency order using NetworkX's topological sort on a directed dependency graph. Cycle detection uses `nx.find_cycle()` and reports the full cycle path as a `LinkError`.

### Model registry

The `ModelRegistry` holds a static primitive table (pre-loaded from the SPICE prefix registry) and a dynamic macro table (populated during linking as definitions are registered). Resolution is case-insensitive and cached.

---

## Stage 5: Bipartite Graph and PyG Projection

`CircuitGraph` builds a flat bipartite graph over a single scope (a `Macro` or the virtual top level). Every node is either a net or a device instance. Every edge represents one terminal connection.

After linking, each `NetConnection` in `instance.nets` carries a resolved `Port`. The graph builder iterates instances, and for each connection emits an edge labelled `ref_des.port_name`. Pre-linking connections (port is None) fall back to just `ref_des`.

### PyG Projection (`to_pyg()`)

`to_pyg()` converts the bipartite graph to a `torch_geometric.data.HeteroData` object. The representation matches the bipartite multigraph described in Kunal et al., "GANA: Graph Convolutional Network Based Automated Netlist Annotation for Analog Circuits," DATE 2020, validated against the ALIGN benchmark circuits.

| Element | Type | Features |
|---|---|---|
| `instance` nodes | `HeteroData["instance"]` | One-hot over model name vocabulary |
| `net` nodes | `HeteroData["net"]` | `[fanout, is_port, is_signal, is_power, is_ground]` |
| `instance → net` edges | `("instance", "connects_to", "net")` | One-hot over terminal vocabulary |
| `net → instance` edges | `("net", "rev_connects_to", "instance")` | Same edge attributes, reversed index |

Net type is classified as follows: nets matching the enclosing `Macro`'s declared ports are `port`; nets matching common power/ground name conventions (`vdd`, `vss`, `0`, `gnd`, etc.) are `power` or `ground`; everything else is `signal`. Port classification takes priority over name heuristics.

The terminal vocabulary is derived automatically from the port names of all registered `Primitive` subclasses: `('a', 'b', 'd', 'g', 's', 'k', 'other')`. `'other'` covers unresolved subcircuit ports. If a new primitive type is added, the vocabulary expands without changes to the graph builder.

Both edge directions are included so message-passing layers can propagate in both directions without separate handling.

The one-hot model encoding is computed over the model name vocabulary present in the current scope. For training across multiple netlists, callers should normalize features or replace the one-hot with learned embeddings before batching.

### Structural validation

Four ALIGN benchmark circuits (telescopic OTA, five-transistor OTA, current mirror OTA, cascode current mirror OTA) are included as integration test fixtures under `tests/fixtures/align/`. The integration tests (`pytest --integration`) verify node counts, bipartite topology, net type classification, and that all MOSFET terminal connections carry named edge features (d/g/s/b with no fallback to 'other').

---

## Planned: Hierarchical Graph and GNN Classifier

The current `CircuitGraph` is flat; it does not recurse into subcircuit instances. The planned `HierarchicalGraph` will maintain lazy subcircuit traversal: subcircuit instances are expanded on demand, with the subcircuit's internal net/instance graph stitched to the parent at the interface ports.

The GNN classifier target is a two-tier approach:

1. Exact subgraph isomorphism (NetworkX VF2) for primitive-level topology matching (current mirror, diff pair).
2. GNN (GraphSAGE or GIN backbone with `HeteroConv`) for higher-level block classification.

Training corpora: SKY130 standard cells, OpenCores gate-level Verilog (via Yosys mapping to SKY130), AnalogGenie/AMSNet analog topologies, and synthetic parameterized templates (OTA, diff pair, telescopic cascode, folded cascode, current mirror) generated via hdl21.
