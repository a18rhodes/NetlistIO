"""Defines supported netlist format types."""

from enum import Enum, auto

__all__ = ["NetlistFormat"]


class NetlistFormat(Enum):
    """Enumeration of supported netlist file formats."""

    SPICE = auto()
