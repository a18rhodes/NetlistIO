"""
Defines SPICE-specific data structures and primitives.

Provides concrete implementations of primitive device types (R, C, L, M, D)
and SPICE-specific netlist representations (Subckt, SpiceNetlist).
"""

import abc
import functools
from dataclasses import dataclass, field
from typing import ClassVar, TextIO

from netlistio.models.generic import Cell, Macro, Netlist, Port, Primitive

__all__ = [
    "Resistor",
    "Capacitor",
    "Inductor",
    "MOSFET",
    "NMOS",
    "PMOS",
    "Diode",
    "Subckt",
    "Model",
    "SpiceNetlist",
    "COMMENT_inst_prefixES",
]

COMMENT_inst_prefixES = ("*", "$", ".")


class _SpicePrimitiveMixin(abc.ABC):
    """Mixin class providing SPICE-specific attributes for primitives."""

    prefix_registry = {}

    def __init_subclass__(cls):
        cls.prefix_registry[cls.inst_prefix] = cls
        return super().__init_subclass__()

    @property
    @abc.abstractmethod
    def inst_prefix(self) -> str:
        """
        The SPICE-style inst_prefix character for this primitive.

        :return: Single-character device inst_prefix (e.g., 'R', 'C', 'M').
        """


class _SpicePassiveMixin:
    """Mixin class for passive SPICE passive devices."""

    registry = set()

    def __init_subclass__(cls):
        cls.registry.add(cls)
        return super().__init_subclass__()


@dataclass(slots=True, eq=False)
class Resistor(Primitive, _SpicePrimitiveMixin, _SpicePassiveMixin):
    """Two-terminal resistor primitive (R)."""

    inst_prefix: ClassVar[str] = "R"
    name: ClassVar[str] = "resistor"
    ports: ClassVar[tuple[Port, ...]] = (Port("a"), Port("b"))


@dataclass(slots=True, eq=False)
class Capacitor(Primitive, _SpicePrimitiveMixin, _SpicePassiveMixin):
    """Two-terminal capacitor primitive (C)."""

    inst_prefix: ClassVar[str] = "C"
    name: ClassVar[str] = "capacitor"
    ports: ClassVar[tuple[Port, ...]] = (Port("a"), Port("b"))


@dataclass(slots=True, eq=False)
class Inductor(Primitive, _SpicePrimitiveMixin, _SpicePassiveMixin):
    """Two-terminal inductor primitive (L)."""

    inst_prefix: ClassVar[str] = "L"
    name: ClassVar[str] = "inductor"
    ports: ClassVar[tuple[Port, ...]] = (Port("a"), Port("b"))


@dataclass(slots=True, eq=False)
class MOSFET(Primitive, _SpicePrimitiveMixin):
    """Four-terminal MOSFET primitive (M)."""

    inst_prefix: ClassVar[str] = "M"
    name: ClassVar[str] = "mosfet"
    ports: ClassVar[tuple[Port, ...]] = (Port("d"), Port("g"), Port("s"), Port("b"))


@dataclass(slots=True, eq=False)
class NMOS(MOSFET):
    """NMOS transistor primitive."""

    inst_prefix: ClassVar[str] = "M"
    name: ClassVar[str] = "nmos"


@dataclass(slots=True, eq=False)
class PMOS(MOSFET):
    """PMOS transistor primitive."""

    inst_prefix: ClassVar[str] = "M"
    name: ClassVar[str] = "pmos"


@dataclass(slots=True, eq=False)
class Diode(Primitive, _SpicePrimitiveMixin):
    """Diode primitive."""

    inst_prefix: ClassVar[str] = "D"
    name: ClassVar[str] = "diode"
    ports: ClassVar[tuple[Port, ...]] = (Port("a"), Port("k"))


class Subckt(Macro, _SpicePrimitiveMixin):
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

    def write(self, stream: TextIO, indent: int = 0):
        super(Model, self).write(stream=stream, indent=indent)
        value = f"Base Type: {self.base_type}\nParams: {self.params}\n"
        stream.write(self._format_with_indent(indent=indent + 1, value=value))


@dataclass
class SpiceNetlist(Netlist):
    """
    SPICE-specific netlist representation.

    Provides SPICE-specific accessors like 'subckts' and 'top_subckt'.
    """

    @property
    def subckts(self) -> list[Macro]:
        """Alias for macros matching SPICE terminology."""
        return self.macros

    @property
    def top(self) -> Macro:
        """Returns top-level instances (parent=None)."""
        return Subckt(
            name="",
            ports=tuple(),
            children=self._top_instances,
        )

    def subckt(self, name: str):
        return self.macro(name=name)

    top_subckt = top  # Alias for SPICE terminology


@functools.lru_cache(maxsize=None)
def get_definition_from_prefix(instance_prefix: str) -> Cell:
    """
    Maps SPICE instance prefix to subcircuit definition keyword.

    :param instance_prefix: Instance prefix character (e.g., 'X').
    :return: Corresponding subcircuit definition keyword (e.g., '.SUBCKT').
    """
    for prefix, cls_ in Subckt.prefix_registry.items():
        if prefix == instance_prefix.upper():
            return cls_
    raise ValueError(f"Instance prefix '{instance_prefix}' does not map to a SPICE subcircuit definition.")


def prefix_registry() -> dict[str, type[Primitive]]:
    """Returns a copy of the SPICE primitive prefix registry."""
    return _SpicePrimitiveMixin.prefix_registry.copy()


def passive_registry() -> set[type[Primitive]]:
    """Returns a copy of the SPICE passive primitive registry."""
    return _SpicePassiveMixin.registry.copy()
