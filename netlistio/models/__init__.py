"""
Data models for netlist representation, parsing, and linking.

Re-exports the complete public model surface from all submodules so consumers
can import from ``netlistio.models`` without knowing the internal layout.
"""

from netlistio.models.format import NetlistFormat
from netlistio.models.generic import (
    Cell,
    Instance,
    InstPort,
    Macro,
    Netlist,
    Port,
    Primitive,
)
from netlistio.models.linking import LinkError, LinkErrorType, LinkResult
from netlistio.models.parsing import (
    WHOLE_FILE,
    IncludeDirective,
    LibraryDirective,
    LibrarySection,
    ParseError,
    ParseRegion,
    ParseResult,
    RegionType,
)
from netlistio.models.spice import (
    MOSFET,
    NMOS,
    PMOS,
    Capacitor,
    Diode,
    Inductor,
    Model,
    Resistor,
    SpiceNetlist,
    Subckt,
    get_definition_from_prefix,
    passive_registry,
    prefix_registry,
)

__all__ = [
    # format
    "NetlistFormat",
    # generic
    "Cell",
    "Instance",
    "InstPort",
    "Macro",
    "Netlist",
    "Port",
    "Primitive",
    # linking
    "LinkError",
    "LinkErrorType",
    "LinkResult",
    # parsing
    "WHOLE_FILE",
    "IncludeDirective",
    "LibraryDirective",
    "LibrarySection",
    "ParseError",
    "ParseRegion",
    "ParseResult",
    "RegionType",
    # spice models
    "Capacitor",
    "Diode",
    "Inductor",
    "MOSFET",
    "Model",
    "NMOS",
    "PMOS",
    "Resistor",
    "SpiceNetlist",
    "Subckt",
    "get_definition_from_prefix",
    "passive_registry",
    "prefix_registry",
]
