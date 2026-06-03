"""
Resolves instance model references and performs topological sorting.

Links parsed instances to their macro or primitive definitions and
topologically sorts macros by dependency order to detect cycles.
"""

import logging
from collections import deque
from pathlib import Path
from typing import Generator

import networkx as nx

from netlistio.models.generic import (
    Cell,
    Instance,
    Macro,
    NetConnection,
    Netlist,
    Primitive,
)
from netlistio.models.linking import LinkError, LinkErrorType, LinkResult
from netlistio.models.parsing import ParseResult

from .registry import ModelRegistry

__all__ = ["link"]

_LOGGER = logging.getLogger(__name__)


def link(parse_result: ParseResult, model_registry: ModelRegistry, netlist_class: type[Netlist]) -> LinkResult:
    """
    Links instances to models and performs topological sort on macros.

    Performs tree-shaking to only include reachable definitions. For
    library-only files (no top-level instances), all parsed definitions
    are included without tree-shaking.

    :param parse_result: Unlinked parse result from parser.
    :param model_registry: Registry for model resolution.
    :param netlist_class: Concrete Netlist subclass to instantiate.
    :return: LinkResult with linked netlist and errors.
    """
    errors: list[LinkError] = []
    definitions_by_name = _build_definition_table(parse_result, errors)
    for name, definition in definitions_by_name.items():
        model_registry.register_definition(name, definition)
    top_instances = [cell for cell in parse_result.cells if isinstance(cell, Instance)]
    # When there are no top-level instances (library-only file), seed the traversal
    # with all defined macros so none are silently dropped by tree-shaking.
    seed_macros = (
        {}
        if top_instances
        else {cell.name: cell for cell in parse_result.cells if isinstance(cell, Macro) and cell.name}
    )
    used_macros, used_primitives = _tree_shake_and_link(top_instances, seed_macros, model_registry, errors)
    sorted_macros, cycle_errors = _topological_sort(used_macros)
    errors.extend(cycle_errors)
    netlist = netlist_class(
        name=Path(parse_result.filepath).name,
        primitives={p.name: p for p in used_primitives},
        macros={macro.name: macro for macro in sorted_macros},
        _top_instances=top_instances,
    )
    return LinkResult(netlist=netlist, errors=errors, top_instances=top_instances)


def _build_definition_table(parse_result: ParseResult, errors: list[LinkError]) -> dict[str, Cell]:
    """
    Builds lookup table for definitions (Macros/Models) and detects duplicates.

    :param parse_result: Unlinked parse result.
    :param errors: Error list to append duplicate errors.
    :return: Dictionary mapping definition names to Cell objects.
    """
    def_by_name = {}
    for cell in parse_result.cells:
        if not isinstance(cell, Instance):
            if cell.name is None:
                errors.append(
                    LinkError(
                        error_type=LinkErrorType.UNNAMED_CELL,
                        message="Found a definition without a name, cannot link it.",
                        affected_cells=[],
                    )
                )
            elif cell.name in def_by_name:
                errors.append(
                    LinkError(
                        error_type=LinkErrorType.DUPLICATE_DEFINITION,
                        message=f"Duplicate definition: {cell.name}",
                        affected_cells=[cell.name],
                    )
                )
            else:
                def_by_name[cell.name] = cell
    return def_by_name


def _tree_shake_and_link(
    roots: list[Instance], seed_macros: dict[str, Macro], model_registry: ModelRegistry, errors: list[LinkError]
) -> tuple[dict[str, Macro], set[Primitive]]:
    """
    Traverses the hierarchy starting from roots, resolving instances and identifying dependencies.

    :param roots: Top-level instances to start traversal.
    :param seed_macros: Macros pre-marked as used (for library-only files).
    :param model_registry: Registry containing all available definitions.
    :param errors: List to append link errors.
    :return: Tuple of (used_macros_dict, used_primitives_set).
    """
    used_macros: dict[str, Macro] = dict(seed_macros)
    used_primitives: set[Primitive] = set()
    visited_macros: set[str] = set(seed_macros)
    queue: deque[Instance] = deque(roots)
    queue.extend(child for macro in seed_macros.values() for child in macro.children if isinstance(child, Instance))
    while queue:
        instance = queue.popleft()
        _resolve_instance_model(instance, model_registry, errors)
        if isinstance(instance.definition, Macro):
            queue.extend(list(_handle_macro(instance, visited_macros, used_macros)))
        elif isinstance(instance.definition, Primitive):
            used_primitives.add(instance.definition)
            _assign_primitive_ports(instance)
    return used_macros, used_primitives


def _handle_macro(
    instance: Instance, visited_macros: set[str], used_macros: dict[str, Macro]
) -> Generator[Instance, None, None]:
    """
    Maps formal ports onto the instance net dict and enqueues unvisited children.

    The net dict keys are net names; after mapping, the values become the formal
    Port objects from the macro definition so downstream analysis can identify
    port roles. If the connection count does not match the port count the mapping
    is skipped and a warning is emitted — the instance remains with None values.

    :param instance: Instance whose definition has already been resolved to a Macro.
    :param visited_macros: Set of macro names already enqueued (deduplication guard).
    :param used_macros: Accumulator of reachable macros for the final netlist.
    :yield: Child Instance objects to process.
    """
    macro = instance.definition
    if len(instance.nets) == len(macro.ports):
        instance.nets = [NetConnection(net, port) for (net, _), port in zip(instance.nets, macro.ports)]
    else:
        _LOGGER.warning(
            "Port count mismatch on instance '%s' of '%s': %d connection(s) provided, %d port(s) defined. "
            "Formal port mapping skipped.",
            instance.name,
            macro.name,
            len(instance.nets),
            len(macro.ports),
        )
    if macro.name not in visited_macros:
        visited_macros.add(macro.name)
        used_macros[macro.name] = macro
        for child in macro.children:
            if isinstance(child, Instance):
                yield child


def _assign_primitive_ports(instance: Instance) -> None:
    """
    Maps formal ports onto a primitive instance by positional order.

    Uses the port list defined on the Primitive class (e.g. d/g/s/b for MOSFET).
    When the same net appears at multiple terminals (e.g. vss vss for source and
    bulk), both entries are preserved and each receives its correct Port.

    :param instance: Instance whose definition is a Primitive.
    """
    primitive = instance.definition
    if len(instance.nets) == len(primitive.ports):
        instance.nets = [NetConnection(net, port) for (net, _), port in zip(instance.nets, primitive.ports)]
    else:
        _LOGGER.warning(
            "Port count mismatch on primitive instance '%s' (%s): %d connection(s), %d port(s). "
            "Formal port mapping skipped.",
            instance.name,
            primitive.name,
            len(instance.nets),
            len(primitive.ports),
        )


def _resolve_instance_model(instance: Instance, model_registry: ModelRegistry, errors: list[LinkError]) -> None:
    """
    Resolves single instance model reference using registry.

    :param instance: Instance to resolve.
    :param model_registry: Model registry for resolution.
    :param errors: Error list to append resolution errors.
    """
    if instance.definition_name is None:
        return
    if model := model_registry.resolve_model(instance.definition_name):
        instance.definition = model
    else:
        errors.append(
            LinkError(
                error_type=LinkErrorType.UNDEFINED_MODEL,
                message=f"Undefined model: {instance.definition_name} (referenced by instance {instance.name})",
                affected_cells=[instance.name],
            )
        )


def _topological_sort(macro_by_name: dict[str, Macro]) -> tuple[list[Macro], list[LinkError]]:
    """
    Topologically sorts macros by dependency order.

    :param macro_by_name: Macro lookup table.
    :return: Tuple of (sorted macros, cycle errors if any).
    """
    graph = _build_dependency_graph(macro_by_name)
    try:
        sorted_names = list(nx.topological_sort(graph))
        return [macro_by_name[name] for name in sorted_names], []
    except nx.NetworkXUnfeasible:
        cycle = nx.find_cycle(graph, orientation="original")
        cycle_path = " → ".join([edge[0] for edge in cycle] + [cycle[0][0]])
        error = LinkError(
            error_type=LinkErrorType.CIRCULAR_DEPENDENCY,
            message=f"Circular dependency detected: {cycle_path}",
            affected_cells=[edge[0] for edge in cycle],
        )
        return list(macro_by_name.values()), [error]


def _build_dependency_graph(macro_by_name: dict[str, Macro]) -> nx.DiGraph:
    """
    Builds directed graph of macro dependencies.

    :param macro_by_name: Macro lookup table.
    :return: NetworkX directed graph with macros as nodes and dependencies as edges.
    """
    graph: nx.DiGraph = nx.DiGraph()
    for macro in macro_by_name.values():
        graph.add_node(macro.name)
    for macro in macro_by_name.values():
        for child in macro.children:
            # Edge: dependency -> consumer, so the dependency sorts first.
            if isinstance(child, Instance) and isinstance(child.definition, Macro):
                graph.add_edge(child.definition.name, macro.name)
    return graph
