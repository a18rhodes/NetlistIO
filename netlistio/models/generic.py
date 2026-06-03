"""Defines format-agnostic data structures for netlists.

Provides abstract base classes and concrete types for representing
circuit hierarchies, including cells, instances, ports, and primitives.
"""

import abc
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import ClassVar, get_origin, get_type_hints

__all__ = ["Port", "NetConnection", "Cell", "Primitive", "Macro", "Instance", "Netlist"]


@dataclass(slots=True)
class _NamedItem(abc.ABC):
    name: str


@dataclass(slots=True)
class Port(_NamedItem):
    """
    Represents a single port on a cell.

    :param name: The port identifier.
    """


@dataclass(slots=True)
class NetConnection:
    """
    A single terminal connection on an instance: the net it is wired to and the
    formal port (filled by the linker; None until then).

    Supports tuple unpacking so existing iteration patterns are unchanged::

        for net, port in instance.nets: ...
    """

    net: str
    port: "Port | None" = None

    def __iter__(self):
        yield self.net
        yield self.port


@dataclass(slots=True)
class InstPort(_NamedItem):
    """
    Represents a port connection on a specific instance.

    :param name: Formal port name (from the cell definition).
    :param inst: The owning Instance.
    :param net: Net name this port is connected to.
    """

    inst: "Instance"
    net: str


@dataclass(slots=True)
class Cell(abc.ABC):
    """
    Base class for all circuit components.

    :param name: Component identifier, or None for anonymous cells (e.g. unnamed
        .model directives). Contrast with :class:`_NamedItem`, whose name is
        always a non-None string.
    """

    name: str | None


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


@dataclass(slots=True)
class Macro(Cell):
    """
    Represents a hierarchical subcircuit definition.

    :param ports: Ordered interface ports for the subcircuit.
    :param children: Contents (Instances, Models, etc.) within this subcircuit.
    """

    ports: tuple[Port, ...] = field(default_factory=tuple)
    children: list[Cell] = field(default_factory=list)

    @property
    def instances(self) -> Generator["Instance", None, None]:
        """
        Yields only the Instance children of this macro.

        Filters out Models and other non-Instance cell types that may appear
        in the children list (e.g., .model directives inside a .subckt).

        :return: Generator of Instance objects.
        """
        yield from (cell for cell in self.children if isinstance(cell, Instance))

    # cached_property is incompatible with slots=True (requires __dict__). Caching
    # would require an explicit slot + manual invalidation on children/port changes.
    @property
    def nets(self) -> dict[str, list]:
        """
        Returns a mapping of net names to their connected InstPort objects.

        Only populated after the linker has resolved formal port assignments.
        Recomputed on each access; capture the result locally when called in
        a tight loop.

        :return: Dictionary of net name → list of InstPort.
        """
        nets: dict[str, list] = {}
        for inst in self.instances:
            for port in inst.ports:
                nets.setdefault(port.net, []).append(port)
        return nets


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
    nets: list["NetConnection"] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)
    definition: Macro | Primitive | None = None
    definition_name: str | None = None
    parent: str | None = None

    # Same cached_property constraint as Macro.nets — slots=True forbids __dict__.
    @property
    def ports(self) -> list["InstPort"]:
        """
        Returns the resolved port connections for this instance.

        Only meaningful after the linker has replaced the net-keyed None
        values with formal Port objects.

        :return: List of InstPort for each net that has a resolved formal port.
        """
        return [InstPort(name=port.name, inst=self, net=net) for net, port in self.nets if port]

    @property
    def is_primitive(self) -> bool:
        """
        Checks if this instance references a primitive device.

        :return: True if model is a Primitive subclass.
        """
        return isinstance(self.definition, Primitive)


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
    def top_instances(self) -> list["Instance"]:
        """
        Returns instances at the top level of the netlist (not inside any subcircuit).

        :return: Copy of the top-level Instance list (callers cannot mutate internal state).
        """
        return list(self._top_instances)

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
