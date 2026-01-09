"""Defines format-agnostic data structures for netlists.

Provides abstract base classes and concrete types for representing
circuit hierarchies, including cells, instances, ports, and primitives.
"""

import abc
from dataclasses import dataclass, field
from functools import lru_cache
from typing import ClassVar, TextIO, get_origin, get_type_hints

__all__ = ["Port", "Cell", "Primitive", "Macro", "Instance", "Netlist"]


class _WritableMixin(abc.ABC):
    @abc.abstractmethod
    def write(self, stream: TextIO, indent: int = 0):
        """write the content of self in a meaningful way"""

    @staticmethod
    def _format_with_indent(indent: int, value: str):
        return f"{' '*indent*4}{value}"


@dataclass(slots=True)
class _NamedItem(_WritableMixin):
    name: str

    def write(self, stream: TextIO, indent: int = 0):
        value = f"{self.__class__.__name__}: {self.name}\n"
        stream.write(self._format_with_indent(indent=indent, value=value))


@dataclass(slots=True)
class Port(_NamedItem):
    """
    Represents a single port on a cell.

    :param name: The port identifier.
    """

    name: str


@dataclass(slots=True)
class Cell(_NamedItem):
    """
    Base class for all circuit components.

    :param name: Component identifier or None for anonymous cells.
    """

    name: str | None

    @classmethod
    @lru_cache(maxsize=None)
    def from_cache(cls, *args, **kwargs):
        """Factory method to cache Cell instances by parameters."""
        return cls(*args, **kwargs)


@dataclass(slots=True, eq=False)
class Primitive(Cell, abc.ABC):
    """
    Base class for primitive device types.

    Primitives are singleton instances cached by type. Subclasses must
    define all attributes as ClassVar to prevent instance field creation.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """
        The canonical model name for this primitive.

        :return: Lowercase primitive identifier (e.g., 'resistor', 'nmos').
        """

    @property
    @abc.abstractmethod
    def ports(self) -> tuple[Port, ...]:
        """
        The ordered port objects for this primitive.

        :return: Tuple of Port objects (e.g., (Port('a'), Port('b')) for resistor).
        """

    def __init_subclass__(cls, **kwargs):
        """Enforce that subclasses define no instance fields."""
        super(Primitive, cls).__init_subclass__(**kwargs)
        own_annotations = cls.__dict__.get("__annotations__", {})
        hints = get_type_hints(cls, include_extras=True)
        invalid_fields = []
        for attr_name in own_annotations:
            if attr_name in hints and get_origin(hints[attr_name]) is not ClassVar:
                invalid_fields.append(attr_name)
        if invalid_fields:
            raise TypeError(
                f"Primitive subclass {cls.__name__} cannot define instance fields: {invalid_fields}. "
                f"All attributes must be ClassVar."
            )

    def __hash__(self) -> int:
        """Hash based on type for cached singletons."""
        return hash(type(self))

    def __eq__(self, other) -> bool:
        """Equality based on type for cached singletons."""
        return type(self) is type(other)

    def write(self, stream: TextIO, indent: int = 0):
        super(Primitive, self).write(stream=stream, indent=indent)
        for port in self.ports:
            port.write(stream=stream, indent=indent + 1)


@dataclass(slots=True)
class Macro(Cell):
    """
    Represents a hierarchical subcircuit definition.

    :param ports: Ordered interface ports for the subcircuit.
    :param children: Contents (Instances, Models, etc.) within this subcircuit.
    """

    ports: tuple[Port, ...] = field(default_factory=tuple)
    # Changed from list[Instance] to list[Cell] to allow nested .models
    children: list[Cell] = field(default_factory=list)

    def write(self, stream: TextIO, indent: int = 0):
        super(Macro, self).write(stream=stream, indent=indent)
        for child in self.children:
            child.write(stream=stream, indent=indent + 1)


@dataclass(slots=True)
class Instance(Cell):
    """
    Represents an instance of a cell within a netlist.

    :param name: Instance identifier.
    :param nets: Port-to-net mappings for this instance.
    :param params: Parameter key-value pairs (e.g., W=1u, L=0.1u).
    :param definition: Resolved cell definition (Macro or Primitive).
    :param definition_name: Unresolved model reference name.
    :param parent: Name of the containing subcircuit.
    """

    name: str
    nets: dict[str, Port | None] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    definition: Macro | Primitive | None = None
    definition_name: str | None = None
    parent: str | None = None

    @property
    def is_primitive(self) -> bool:
        """
        Checks if this instance references a primitive device.

        :return: True if model is a Primitive subclass.
        """
        return isinstance(self.definition, Primitive)

    def write(self, stream: TextIO, indent: int = 0):
        Cell.write(self, stream=stream, indent=indent)
        for net, port in self.nets.items():
            value = f"Net: {net}\n"
            if port is not None:
                value = f"Port: {port.name} -> {value}"
            stream.write(self._format_with_indent(indent=indent + 1, value=value))
        stream.write(
            self._format_with_indent(
                indent=indent + 1, value=", ".join(f"{k}={v}" for k, v in self.params.items()) + "\n"
            )
        )
        stream.write(self._format_with_indent(indent=indent + 1, value="Model:\n"))
        if self.definition:
            self.definition.write(stream=stream, indent=indent + 2)
        else:
            stream.write(self._format_with_indent(indent=indent + 2, value=f"Unresolved: {self.definition_name}\n"))


@dataclass(slots=True)
class Netlist(_NamedItem):
    """
    Abstract base class for complete netlist representations.

    :param primitives: List of primitive device types used.
    :param macros: List of subcircuit definitions.
    :param _top_instances: Instances at the top level (no parent).
    """

    primitives: dict[str, Primitive] = field(default_factory=dict)
    macros: dict[str, Macro] = field(default_factory=dict)
    _top_instances: list[Instance] = field(default_factory=list)

    @property
    def cells(self) -> list[Cell]:
        """
        Returns all cells in the netlist (primitives, macros, instances).

        :return: List of all Cell objects in the netlist.
        """

        return [*self.primitives.values(), *self.macros.values(), *self._top_instances]

    @property
    @abc.abstractmethod
    def top(self) -> Macro:
        """
        Constructs a virtual top-level macro containing orphan instances.

        :return: A Macro representing the top-level netlist scope.
        """

    def write(self, stream: TextIO, indent: int = 0):
        super(Netlist, self).write(stream=stream, indent=indent)
        stream.write(self._format_with_indent(indent=indent, value="Primitives:\n"))
        for primitive in self.primitives.values():
            primitive.write(stream=stream, indent=indent + 1)
        stream.write(self._format_with_indent(indent=indent, value="Macros:\n"))
        for macro in self.macros.values():
            macro.write(stream=stream, indent=indent + 1)
        stream.write(self._format_with_indent(indent=indent, value="Top-Level Instances:\n"))
        stream.write(self._format_with_indent(indent=indent + 1, value="(virtual top)\n"))
        for instance in self._top_instances:
            instance.write(stream=stream, indent=indent + 2)
