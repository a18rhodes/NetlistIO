"""
Defines SPICE-specific data structures and primitives.

Provides concrete implementations of primitive device types (R, C, L, M, D)
and SPICE-specific netlist representations (Subckt, SpiceNetlist).
"""

import abc
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Mapping

from netlistio.models.generic import Cell, Macro, Netlist, Port, Primitive

__all__ = ["Resistor", "Capacitor", "Inductor", "MOSFET", "NMOS", "PMOS", "Diode", "Subckt", "Model", "SpiceNetlist"]


class _SpicePrefixMixin(abc.ABC):
    """Mixin that auto-registers SPICE classes by their instance prefix.

    Only classes that declare ``inst_prefix`` in their own namespace register;
    subclasses that merely inherit a prefix (e.g. NMOS/PMOS reusing 'M' from
    MOSFET) are skipped, so they never clobber the base mapping. Registration is
    last-write-wins, which is required because ``@dataclass(slots=True)`` rebuilds
    the class and re-triggers this hook with the final (slotted) class object.
    """

    prefix_registry: dict[str, type] = {}

    def __init_subclass__(cls):
        if "inst_prefix" in cls.__dict__:
            cls.prefix_registry[cls.inst_prefix] = cls
        return super().__init_subclass__()

    @property
    @abc.abstractmethod
    def inst_prefix(self) -> str:
        """
        The SPICE-style inst_prefix character for this primitive.

        :return: Single-character device inst_prefix (e.g., 'R', 'C', 'M').
        """


class _SpicePassiveRegistry:  # pylint: disable=too-few-public-methods
    """Mixin that auto-registers passive SPICE devices (R, C, L)."""

    registry: set[type] = set()

    def __init_subclass__(cls):
        cls.registry.add(cls)
        return super().__init_subclass__()


@dataclass(slots=True, eq=False)
class Resistor(Primitive, _SpicePrefixMixin, _SpicePassiveRegistry):
    """Two-terminal resistor primitive (R)."""

    inst_prefix: ClassVar[str] = "R"
    name: ClassVar[str] = "resistor"
    ports: ClassVar[tuple[Port, ...]] = (Port("a"), Port("b"))


@dataclass(slots=True, eq=False)
class Capacitor(Primitive, _SpicePrefixMixin, _SpicePassiveRegistry):
    """Two-terminal capacitor primitive (C)."""

    inst_prefix: ClassVar[str] = "C"
    name: ClassVar[str] = "capacitor"
    ports: ClassVar[tuple[Port, ...]] = (Port("a"), Port("b"))


@dataclass(slots=True, eq=False)
class Inductor(Primitive, _SpicePrefixMixin, _SpicePassiveRegistry):
    """Two-terminal inductor primitive (L)."""

    inst_prefix: ClassVar[str] = "L"
    name: ClassVar[str] = "inductor"
    ports: ClassVar[tuple[Port, ...]] = (Port("a"), Port("b"))


@dataclass(slots=True, eq=False)
class MOSFET(Primitive, _SpicePrefixMixin):
    """Four-terminal MOSFET primitive (M)."""

    inst_prefix: ClassVar[str] = "M"
    name: ClassVar[str] = "mosfet"
    ports: ClassVar[tuple[Port, ...]] = (Port("d"), Port("g"), Port("s"), Port("b"))


@dataclass(slots=True, eq=False)
class NMOS(MOSFET):
    """NMOS transistor primitive. Inherits the 'M' prefix from MOSFET."""

    name: ClassVar[str] = "nmos"


@dataclass(slots=True, eq=False)
class PMOS(MOSFET):
    """PMOS transistor primitive. Inherits the 'M' prefix from MOSFET."""

    name: ClassVar[str] = "pmos"


@dataclass(slots=True, eq=False)
class Diode(Primitive, _SpicePrefixMixin):
    """Diode primitive."""

    inst_prefix: ClassVar[str] = "D"
    name: ClassVar[str] = "diode"
    ports: ClassVar[tuple[Port, ...]] = (Port("a"), Port("k"))


class Subckt(Macro, _SpicePrefixMixin):
    """SPICE subcircuit definition (.SUBCKT)."""

    inst_prefix: ClassVar[str] = "X"


@dataclass(slots=True)
class Model(Cell):
    """
    Represents a .model directive.

    Example: .model my_nmos nmos level=54
    name: "my_nmos"
    base_type: "nmos"
    params: {"level": "54"}
    """

    base_type: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SpiceNetlist(Netlist):
    """
    SPICE-specific netlist representation.

    Provides SPICE-specific accessors like 'subckts' and 'top_subckt'.
    """

    @property
    def subckts(self) -> dict[str, Macro]:
        """Alias for macros matching SPICE terminology."""
        return self.macros

    @property
    def top(self) -> Macro:
        """Returns top-level instances (parent=None)."""
        return Subckt(name="", ports=tuple(), children=self._top_instances)

    @property
    def top_subckt(self) -> Macro:
        """Alias for top matching SPICE terminology."""
        return self.top

    def subckt(self, name: str) -> Macro | None:
        """
        Looks up a subcircuit definition by name.

        :param name: Subcircuit name.
        :return: Matching Macro, or None if not found.
        """
        return self.macros.get(name)


# Frozen views built once after all classes have registered. The underlying
# tables are immutable from here on, so sharing them is safe and lock-free.
_PREFIX_REGISTRY: Mapping[str, type] = MappingProxyType(dict(_SpicePrefixMixin.prefix_registry))
_PASSIVE_TYPES: frozenset[type] = frozenset(_SpicePassiveRegistry.registry)


def get_definition_from_prefix(instance_prefix: str) -> type[Cell]:
    """
    Maps a SPICE instance prefix to its definition class.

    :param instance_prefix: Instance prefix character (e.g., 'X').
    :return: Corresponding definition class (e.g., Subckt for 'X').
    :raises ValueError: If the prefix maps to no known SPICE definition.
    """
    if cls_ := _PREFIX_REGISTRY.get(instance_prefix.upper()):
        return cls_
    raise ValueError(f"Instance prefix '{instance_prefix}' does not map to a SPICE subcircuit definition.")


def prefix_registry() -> Mapping[str, type]:
    """Returns the immutable SPICE prefix-to-class registry."""
    return _PREFIX_REGISTRY


def passive_registry() -> frozenset[type]:
    """Returns the immutable set of passive SPICE primitive classes."""
    return _PASSIVE_TYPES
