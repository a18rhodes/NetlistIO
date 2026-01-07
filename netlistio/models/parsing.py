"""
Defines parsing infrastructure for netlist ingestion.

Provides region types, error records, and result containers for the
parsing phase where raw text is converted to structured data.
"""

from dataclasses import dataclass, field
from enum import Enum, auto

__all__ = ["RegionType", "ParseError", "ParseResult", "ParseRegion", "IncludeDirective", "LibraryDirective"]


@dataclass(slots=True, frozen=True)
class IncludeDirective:
    """Represents a .include directive."""

    filepath: str
    source_file: str
    strict: bool = True


@dataclass(slots=True, frozen=True)
class LibraryDirective(IncludeDirective):
    """Represents a .lib directive."""

    section: str | None = None


class RegionType(Enum):
    """
    Enumeration of parsing region types.

    GLOBAL: Top-level netlist scope outside any subcircuit.
    MACRO: Region within a subcircuit definition.
    """

    GLOBAL = auto()
    MACRO = auto()


@dataclass(slots=True)
class ParseError:
    """
    Records a single parsing error with source context.

    :param line_number: 1-indexed line number where error occurred.
    :param message: Human-readable error description.
    :param line_content: Optional raw line content for debugging.
    """

    line_number: int
    message: str
    line_content: str | None = None


@dataclass(slots=True)
class ParseResult:
    """
    Encapsulates the result of a parsing operation.

    :param filepath: The path to the file that was parsed
    :param cells: List of successfully parsed cells (Macros or other).
    :param errors: List of errors encountered during parsing.
    """

    filepath: str
    cells: list = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    includes: list[IncludeDirective] = field(default_factory=list)


@dataclass(slots=True)
class ParseRegion:
    """
    Defines a byte-range region for parallel parsing.

    :param filepath: The path to the file that is being parsed here.
    :param start_byte: Starting byte offset in the file.
    :param end_byte: Ending byte offset (exclusive).
    :param region_type: Scope category (GLOBAL or MACRO).
    :param context_delimiter: Format-specific delimiter (e.g., '.SUBCKT').
    :param context_name: Name of the enclosing context (e.g., subcircuit name).
    """

    filepath: str
    start_byte: int
    end_byte: int
    region_type: RegionType
    context_delimiter: str | None = None
    context_name: str | None = None
