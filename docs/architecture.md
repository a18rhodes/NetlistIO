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

Files are opened with `mmap(ACCESS_READ)`. The practical advantages of mmap in this context are:

- Cache bypass: when data is already in the OS page cache, mmap access is a TLB miss and page table lookup; the kernel is not entered at all. `read()` always copies from the page cache into a userspace buffer even when the data is already in RAM. This matters on repeat parses and for include files referenced from multiple places.
- Shared pages across workers: processes mapping the same file share physical pages in the page cache. With `read()`, each process gets its own buffer copy.
- Ergonomic slice dispatch: workers receive a memoryview slice rather than `(path, start_byte, end_byte)` plus per-worker file opens and seek calls.

For the sequential scanning phase, benchmarks show buffered `read()` and mmap are roughly equivalent because kernel read-ahead prefetching covers most of the page fault latency. The gains are more pronounced for the worker dispatch phase, which jumps to non-sequential byte offsets. Lazy page loading (proportional memory use) is a side effect of the OS page mapping model, not an independent benefit.

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
