"""
Resolves instance model references and performs topological sorting.

Links parsed instances to their macro or primitive definitions and
topologically sorts macros by dependency order to detect cycles.
"""

from pathlib import Path

import networkx as nx

from netlistio.models.generic import Instance, Macro, Netlist, Primitive
from netlistio.models.linking import LinkError, LinkErrorType, LinkResult
from netlistio.models.parsing import ParseResult

from .registry import ModelRegistry

__all__ = ["link"]


def link(parse_result: ParseResult, model_registry: ModelRegistry, netlist_class: Netlist) -> LinkResult:
    """
    Links instances to models and performs topological sort on macros.

    :param parse_result: Unlinked parse result from parser.
    :param model_registry: Optional dynamic model registry for library resolution.
    :return: LinkResult with linked netlist and errors.
    """
    errors: list[LinkError] = []
    macro_by_name = _build_macro_table(parse_result, errors)

    # Add parsed macros with lowercase keys
    for name, macro in macro_by_name.items():
        model_registry.static_macros[name.lower()] = macro

    instances = _resolve_instances(parse_result, model_registry, errors)
    for instance in instances:
        if instance.definition:
            instance.nets = dict(zip(instance.nets, instance.definition.ports))
    sorted_macros, cycle_errors = _topological_sort(macro_by_name)
    errors.extend(cycle_errors)
    primitives = _collect_primitives(instances)
    top_instances = [inst for inst in instances if inst.parent is None]
    netlist = netlist_class(
        name=Path(parse_result.filepath).name, primitives=primitives, macros=sorted_macros, _top_instances=top_instances
    )
    return LinkResult(netlist=netlist, errors=errors, top_instances=top_instances)


def _build_macro_table(parse_result: ParseResult, errors: list[LinkError]) -> dict[str, Macro]:
    """
    Builds macro lookup table and detects duplicates.

    :param parse_result: Unlinked parse result.
    :param errors: Error list to append duplicate errors.
    :return: Dictionary mapping macro names to Macro objects.
    """
    macro_by_name = {}
    for cell in parse_result.cells:
        if isinstance(cell, Macro):
            if cell.name is None:
                errors.append(
                    LinkError(
                        error_type=LinkErrorType.UNNAMED_CELL,
                        message="Found a cell without a name, cannot link it to a model",
                        affected_cells=[],
                    )
                )
            elif cell.name in macro_by_name:
                errors.append(
                    LinkError(
                        error_type=LinkErrorType.DUPLICATE_DEFINITION,
                        message=f"Duplicate subcircuit definition: {cell.name}",
                        affected_cells=[cell.name],
                    )
                )
            else:
                macro_by_name[cell.name] = cell
    return macro_by_name


def _resolve_instances(
    parse_result: ParseResult, model_registry: ModelRegistry, errors: list[LinkError]
) -> list[Instance]:
    """
    Resolves all instance model references using the model registry.

    :param parse_result: Unlinked parse result.
    :param model_registry: Model registry for static and dynamic resolution.
    :param errors: Error list to append resolution errors.
    :return: List of all instances (top-level and nested).
    """
    instances = []
    for cell in parse_result.cells:
        if isinstance(cell, Instance):
            _resolve_instance_model(cell, model_registry, errors)
            instances.append(cell)
        elif isinstance(cell, Macro):
            for child in cell.children:
                _resolve_instance_model(child, model_registry, errors)
                instances.append(child)
    return instances


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


def _topological_sort(
    macro_by_name: dict[str, Macro],
) -> tuple[list[Macro], list[LinkError]]:
    """
    Topologically sorts macros by dependency order.

    :param macro_by_name: Macro lookup table.
    :return: Tuple of (sorted macros, cycle errors if any).
    """
    graph = _build_dependency_graph(macro_by_name)
    try:
        sorted_names = list(nx.topological_sort(graph))
        return [macro_by_name[name] for name in sorted_names], []
    except nx.NetworkXError:
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
        for instance in macro.children:
            if isinstance(instance.definition, Macro):
                graph.add_edge(macro.name, instance.definition.name)
    return graph


def _collect_primitives(instances: list[Instance]) -> list[Primitive]:
    """
    Collects unique primitive types from resolved instances.

    :param instances: List of all instances.
    :return: List of unique Primitive objects.
    """
    primitives = set()
    for instance in instances:
        if isinstance(instance.definition, Primitive):
            primitives.add(instance.definition)
    return list(primitives)
