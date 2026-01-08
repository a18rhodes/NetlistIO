"""
Orchestration layer for reading netlists.

This module provides the `NetlistReader` interface and format-specific
implementations (like `SpiceReader`) that compose the Scanner, Parser,
Linker, and Registry components into a single execution pipeline.
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from netlistio.ingestor.includes import IncludeResolver
from netlistio.ingestor.library import LibraryProcessor
from netlistio.ingestor.linker import link
from netlistio.ingestor.parser import Parser
from netlistio.ingestor.registry import ModelRegistry
from netlistio.ingestor.scanner import Scanner
from netlistio.ingestor.spice import SpiceChunkParserFactory, SpiceScanStrategy, SpiceModelResolver
from netlistio.models.generic import Netlist
from netlistio.models.spice import SpiceNetlist

__all__ = ["NetlistReader", "SpiceReader"]


class NetlistReader(ABC):
    """Abstract base class for netlist readers."""

    @abstractmethod
    def read(self, filepath: Path, num_workers: Optional[int] = None) -> Netlist:
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
    1. Scan & Resolve Includes (Scanner + IncludeResolver)
    2. Process Libraries (LibraryProcessor + ModelRegistry)
    3. Parse Content (Multiprocessing Parser)
    4. Link Hierarchy (Linker)
    """

    def read(self, filepath: Path, num_workers: Optional[int] = None) -> Netlist:
        num_workers = num_workers or os.cpu_count() or 1
        root_path = Path(filepath).resolve()

        # --- Phase 1: Discovery (Scanning & Includes) ---
        scan_strategy = SpiceScanStrategy()

        # We need a temporary scanner just to resolve includes from the root file
        # The IncludeResolver uses the scan_strategy to find .include lines
        include_resolver = IncludeResolver(scan_strategy)
        # resolve_includes builds the dependency tree
        all_files, library_directives = include_resolver.resolve_includes(root_path)

        # --- Phase 2: Library Registration ---
        library_processor = LibraryProcessor()
        model_registry = ModelRegistry()
        # Use the Resolver now located in netlistio.ingestor.spice
        model_registry.model_resolver = SpiceModelResolver()

        for lib_directive in library_directives:
            lib_path = Path(lib_directive.filepath)
            try:
                # Extract byte-range for the specific library section (.lib file tt)
                lib_content = library_processor.extract_section(lib_path, lib_directive.section)
                model_registry.register_library_content(str(lib_path), lib_content)
            except ValueError as e:
                print(f"Error processing library {lib_path}: {e}")
                # We continue, as linking might succeed anyway if models are unused
                pass

        # --- Phase 3: Parallel Parsing ---
        # Re-initialize scanner for the parser to use on the root file
        # Note: In a full implementation, we'd parse ALL files returned by include_resolver
        parser_scanner = Scanner(root_path, scan_strategy)

        parser = Parser(
            filepath=root_path,
            scanner=parser_scanner,  # The scanner is iterable, yielding ParseRegions
            chunk_parser_factory=SpiceChunkParserFactory(),
        )

        parse_result = parser.parse(num_workers=num_workers)

        # --- Phase 4: Linking ---
        link_result = link(parse_result, model_registry, SpiceNetlist)

        if link_result.errors:
            print(f"Linking completed with {len(link_result.errors)} errors.")
            for error in link_result.errors:
                print(f"  - {error.message}: {', '.join(error.affected_cells)}")

        return link_result.netlist
