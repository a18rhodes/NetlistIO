"""
Orchestration layer for reading netlists.

This module provides the `NetlistReader` interface and format-specific
implementations (like `SpiceReader`) that compose the Scanner, Compiler,
Linker, and Registry components into a single execution pipeline.
"""

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from netlistio.ingestor.compiler import Compiler
from netlistio.ingestor.linker import link
from netlistio.ingestor.parser import Parser
from netlistio.ingestor.registry import ModelRegistry
from netlistio.ingestor.scanner import Scanner
from netlistio.ingestor.spice import (
    SpiceChunkParserFactory,
    SpiceLibraryProcessor,
    SpiceScanStrategy,
)
from netlistio.models.generic import Netlist, Primitive
from netlistio.models.parsing import ParseRegion
from netlistio.models.spice import SpiceNetlist, prefix_registry

__all__ = ["NetlistReader", "SpiceReader"]

_LOGGER = logging.getLogger(__name__)


def _spice_scanner_factory(filepath: Path) -> Scanner:
    """Builds a SPICE scanner for the given file."""
    return Scanner(filepath, SpiceScanStrategy())


def _spice_parser_factory(filepath: Path, regions: Iterable[ParseRegion]) -> Parser:
    """Builds a SPICE parser over the given regions."""
    return Parser(filepath, regions, SpiceChunkParserFactory())


class NetlistReader(ABC):
    """Abstract base class for netlist readers."""

    @abstractmethod
    def read(self, filepath: Path, num_workers: int | None = None) -> Netlist:
        """
        Reads a netlist file and returns a linked Netlist object.

        :param filepath: Path to the entry point file.
        :param num_workers: Number of parallel workers (default: CPU count).
        :return: Fully linked and resolved Netlist.
        """


class SpiceReader(NetlistReader):
    """
    Orchestrator for reading SPICE netlists.

    Composes the following pipeline:
    1. Compile (Compiler): Iterative discovery and parsing of files/regions.
    2. Registry Setup: Pre-loads static SPICE primitives.
    3. Link (Linker): Tree-shaking resolution of instances to models/subckts.
    """

    def read(self, filepath: Path, num_workers: int | None = None) -> Netlist:
        num_workers = num_workers or os.cpu_count() or 1
        root_path = Path(filepath).resolve()
        # --- Phase 1: Compilation (Discovery & Parsing) ---
        compiler = Compiler(
            root_filepath=root_path,
            parser_factory=_spice_parser_factory,
            scanner_factory=_spice_scanner_factory,
            library_factory=SpiceLibraryProcessor,
            num_workers=num_workers,
        )
        parse_result = compiler.compile()

        # --- Phase 2: Registry Setup ---
        # Pre-load the SPICE primitive registry so the linker can resolve bare
        # model references (e.g. "nmos", "resistor") that have no .model definition.
        model_registry = ModelRegistry(
            static_primitives={cls.name: cls() for cls in set(prefix_registry().values()) if issubclass(cls, Primitive)}
        )

        # --- Phase 3: Linking & Tree-Shaking ---
        # The link function now performs tree-shaking, meaning it starts from
        # top-level instances and only links definitions that are actually used.
        link_result = link(parse_result, model_registry, SpiceNetlist)
        self._report_link_errors(link_result.errors)
        return link_result.netlist

    @staticmethod
    def _report_link_errors(errors: list) -> None:
        """Emits linking errors via the logging framework."""
        if not errors:
            return
        _LOGGER.warning("Linking completed with %d errors.", len(errors))
        for error in errors:
            _LOGGER.warning("[%s] %s", error.error_type.name, error.message)
            if error.affected_cells:
                _LOGGER.warning("    Affected: %s", ", ".join(error.affected_cells[:5]))
