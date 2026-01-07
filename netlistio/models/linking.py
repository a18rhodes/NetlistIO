"""
Defines linking infrastructure for model resolution.

Provides error types, error records, and result containers for the
linking phase where instance references are resolved to definitions.
"""

from dataclasses import dataclass, field
from enum import Enum, auto

from .generic import Instance, Netlist

__all__ = ["LinkErrorType", "LinkError", "LinkResult"]


class LinkErrorType(Enum):
    """
    Enumeration of error types encountered during linking.

    UNDEFINED_MODEL: Instance references a non-existent cell.
    CIRCULAR_DEPENDENCY: Subcircuit hierarchy contains a cycle.
    DUPLICATE_DEFINITION: Multiple definitions for the same cell name.
    """

    UNDEFINED_MODEL = auto()
    UNNAMED_CELL = auto
    CIRCULAR_DEPENDENCY = auto()
    DUPLICATE_DEFINITION = auto()


@dataclass(slots=True)
class LinkError:
    """
    Records a single linking error with context.

    :param error_type: Category of linking failure.
    :param message: Human-readable error description.
    :param affected_cells: List of cell names involved in the error.
    """

    error_type: LinkErrorType
    message: str
    affected_cells: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LinkResult:
    """
    Encapsulates the result of a linking operation.

    :param netlist: The netlist with resolved references.
    :param errors: List of errors encountered during linking.
    :param top_instances: Instances at the top level (no parent).
    """

    netlist: Netlist
    errors: list[LinkError] = field(default_factory=list)
    top_instances: list[Instance] = field(default_factory=list)
