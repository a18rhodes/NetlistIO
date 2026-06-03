"""
Human-readable tree rendering for netlist models.

Keeps presentation concerns (indentation, truncation, summarization) out of the
domain model. Dispatch is by node type, so a new model type registers a single
method here rather than carrying its own writer.
"""

from collections import Counter
from functools import singledispatchmethod
from typing import TextIO

from netlistio.models.generic import Cell, Instance, Macro, Netlist, Port, Primitive

__all__ = [
    "NetlistPrinter",
    "DEFAULT_CHARS_PER_INDENT",
    "DEFAULT_INDENT_CHAR",
    "DEFAULT_PARAM_LIMIT",
    "DEFAULT_MODEL_SUMMARY_THRESHOLD",
]

DEFAULT_CHARS_PER_INDENT = 4
DEFAULT_INDENT_CHAR = " "
DEFAULT_INDENT_COUNT = 4
DEFAULT_PARAM_LIMIT = 5
DEFAULT_MODEL_SUMMARY_THRESHOLD = 3


class NetlistPrinter:
    """Renders netlist model trees as indented, human-readable text."""

    def __init__(
        self,
        stream: TextIO,
        indent_char: str = DEFAULT_INDENT_CHAR,
        indent_count: int = DEFAULT_INDENT_COUNT,
        param_limit: int = DEFAULT_PARAM_LIMIT,
        model_summary_threshold: int = DEFAULT_MODEL_SUMMARY_THRESHOLD,
    ):
        """
        :param stream: Destination text stream for rendered output.
        """
        self._stream = stream
        self._indent_char = indent_char
        self._indent_count = indent_count
        self._param_limit = param_limit
        self._model_summary_threshold = model_summary_threshold

    def print(self, node: Cell | Netlist | Port, indent: int = 0) -> None:
        """
        Renders a node and its descendants to the stream.

        :param node: Root node to render.
        :param indent: Starting indentation depth.
        """
        self._render(node, indent)

    def _emit(self, value: str, indent: int) -> None:
        self._stream.write(f"{self._indent_char * self._indent_count * indent}{value}")

    def _header(self, node: Cell | Netlist | Port, indent: int) -> None:
        name = node.name if node.name is not None else "<anonymous>"
        self._emit(f"{node.__class__.__name__}: {name}\n", indent)

    def _format_params(self, params: dict[str, str]) -> str:
        items = list(params.items())
        if len(items) > self._param_limit:
            shown = ", ".join(f"{k}={v}" for k, v in items[: self._param_limit])
            return f"{shown}, ... ({len(items) - self._param_limit} more)"
        return ", ".join(f"{k}={v}" for k, v in items)

    @singledispatchmethod
    def _render(self, node: Cell | Netlist, indent: int) -> None:
        """
        Render any model-like node (any cell exposing base_type/params).

        Duck-typed to keep this layer format-agnostic.
        """
        self._header(node, indent)
        if hasattr(node, "base_type"):
            self._emit(f"Base Type: {node.base_type}\n", indent + 1)
            self._emit(f"Params: {{{self._format_params(node.params)}}}\n", indent + 1)

    @_render.register
    def _render_primitive(self, node: Primitive, indent: int) -> None:
        self._header(node, indent)
        for port in node.ports:
            self._render(port, indent + 1)

    @_render.register
    def _render_macro(self, node: Macro, indent: int) -> None:
        self._header(node, indent)
        models, others = self._partition_children(node)
        if len(models) > self._model_summary_threshold:
            self._render_many_models(models, indent + 1)
        else:
            self._render_models(models, indent + 1)
        for child in others:
            self._render(child, indent + 1)

    @_render.register
    def _render_instance(self, node: Instance, indent: int) -> None:
        self._header(node, indent)
        self._render_instance_nets(node, indent + 1)
        self._render_instance_params(node, indent + 1)
        self._emit("Definition:\n", indent + 1)
        if node.definition:
            self._render(node.definition, indent + 2)
        else:
            self._emit(f"Unresolved: {node.definition_name}\n", indent + 2)

    @_render.register
    def _render_netlist(self, node: Netlist, indent: int) -> None:
        self._header(node, indent)
        self._emit("Primitives:\n", indent)
        for primitive in node.primitives.values():
            self._render(primitive, indent + 1)
        self._emit("Macros:\n", indent)
        for macro in node.macros.values():
            self._render(macro, indent + 1)
        self._emit("Top-Level Instances:\n", indent)
        self._emit("(virtual top)\n", indent + 1)
        for instance in node.top_instances:
            self._render(instance, indent + 2)

    @staticmethod
    def _partition_children(node: Cell) -> tuple[list[Cell], list[Cell]]:
        models = []
        others = []
        for child in node.children:
            if hasattr(child, "base_type"):
                models.append(child)
            else:
                others.append(child)
        return models, others

    def _render_many_models(self, models: list[Cell], indent: int) -> None:
        counts = Counter(getattr(model, "base_type", "unknown") for model in models)
        summary = ", ".join(f"{count}x {base}" for base, count in counts.items())
        self._emit(f"Local Definitions: {len(models)} total ({summary})\n", indent + 1)

    def _render_models(self, models: list[Cell], indent: int) -> None:
        for model in models:
            self._render(model, indent + 1)

    def _render_instance_nets(self, instance: Instance, indent: int) -> None:
        for net, port in instance.nets:
            value = f"Net: {net}\n"
            if port is not None:
                value = f"Port: {port.name} -> {value}"
            self._emit(value, indent + 1)

    def _render_instance_params(self, instance: Instance, indent: int) -> None:
        if params_str := self._format_params(instance.params):
            self._emit(f"{params_str}\n", indent + 1)
