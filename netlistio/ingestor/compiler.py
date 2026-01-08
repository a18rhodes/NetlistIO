"""
The Compiler orchestration engine.

Replaces the legacy 'Flattener'. The Compiler treats the netlist as a
graph of translation units. It iteratively parses files and library sections,
resolving paths and queueing new work until the entire graph is built.
"""

from collections import deque
from pathlib import Path
from typing import Callable

from netlistio.ingestor.library import LibraryProcessor
from netlistio.ingestor.parser import Parser
from netlistio.ingestor.scanner import Scanner
from netlistio.models.parsing import (
    IncludeDirective,
    LibraryDirective,
    ParseRegion,
    ParseResult,
    RegionType,
)

__all__ = ["Compiler"]


class Compiler:
    """
    Orchestrates the parsing of a full netlist hierarchy.

    Manages the parsing queue, path resolution, and library section extraction.
    """

    def __init__(
        self,
        root_filepath: Path,
        parser_factory: Callable[[Path, Scanner], Parser],
        scanner_factory: Callable[[Path], Scanner],
    ):
        """
        Initialize the compiler.

        :param root_filepath: Entry point of the netlist.
        :param parser_factory: Callable to create new Parsers.
        :param scanner_factory: Callable to create new Scanners.
        """
        self.root = Path(root_filepath).resolve()
        self.parser_factory = parser_factory
        self.scanner_factory = scanner_factory
        self.library_processor = LibraryProcessor()

        # State
        self.visited_regions: set[str] = set()  # Key: "filepath:start-end"
        self.queue: deque[ParseRegion] = deque()
        self.aggregated_result = ParseResult(filepath=str(self.root))

    def compile(self) -> ParseResult:
        """
        Execute the compilation process.

        Iteratively processes the parse queue until all dependencies are resolved.
        """
        # 1. Seed queue with the root file
        root_region = self._create_file_region(self.root)
        self._enqueue(root_region)

        # 2. Process Queue
        while self.queue:
            region = self.queue.popleft()

            # Parse this specific region
            result = self._parse_region(region)

            # Aggregate Results
            self.aggregated_result.cells.extend(result.cells)
            self.aggregated_result.errors.extend(result.errors)

            # Process Dependencies
            for directive in result.includes:
                self._handle_directive(directive, region.filepath)

        return self.aggregated_result

    def _enqueue(self, region: ParseRegion):
        """Add region to queue if not already visited."""
        key = f"{region.filepath}:{region.start_byte}-{region.end_byte}"
        if key not in self.visited_regions:
            self.visited_regions.add(key)
            self.queue.append(region)

    def _parse_region(self, region: ParseRegion) -> ParseResult:
        """
        Parses a specific region of a file.

        Handles both full files (scanning for macros first) and strict
        byte-ranges (library sections, treated as flat lists of models).
        """
        path = Path(region.filepath)

        # Case A: Whole File. Scan it to find subckts structure.
        if region.start_byte == 0 and region.end_byte == -1:
            scanner = self.scanner_factory(path)
            regions = scanner.scan()  # Returns deque of regions in file

            # We parse all regions found in this file
            parser = self.parser_factory(path, regions)
            return parser.parse()

        # Case B: Byte Slice (e.g., .lib section).
        # We assume LIB sections are lists of models/subckts without further nesting.
        else:
            # Create a synthetic single-item scanner for the Parser API
            single_region_scanner = [region]
            parser = self.parser_factory(path, single_region_scanner)
            return parser.parse()

    def _handle_directive(self, directive: IncludeDirective, context_filepath: str):
        """Resolves path and adds new work to queue."""

        # 1. Resolve Path
        try:
            path = self._resolve_path(directive.filepath, Path(context_filepath).parent)
        except FileNotFoundError:
            if directive.strict:
                # Log error but continue
                print(f"Warning: Could not resolve include '{directive.filepath}' in {context_filepath}")
            return

        # 2. Create Region
        if isinstance(directive, LibraryDirective) and directive.section:
            # It's a Section (.lib file section)
            try:
                section_info = self.library_processor.find_section(path, directive.section)
                region = ParseRegion(
                    filepath=str(path),
                    start_byte=section_info.start_byte,
                    end_byte=section_info.end_byte,
                    region_type=RegionType.GLOBAL,
                )
                self._enqueue(region)
            except ValueError:
                print(f"Warning: Section '{directive.section}' not found in {directive.filepath}")
        else:
            # It's a full file (.include or .lib file without section)
            region = self._create_file_region(path)
            self._enqueue(region)

    def _create_file_region(self, path: Path) -> ParseRegion:
        """Create a region representing an entire file."""
        return ParseRegion(
            filepath=str(path),
            start_byte=0,
            end_byte=-1,  # Indicator for "Whole File"
            region_type=RegionType.GLOBAL,
        )

    def _resolve_path(self, filename: str, base_dir: Path) -> Path:
        """Resolve absolute path from filename relative to base or root."""
        # 1. Try absolute
        p = Path(filename)
        if p.is_absolute() and p.exists():
            return p

        # 2. Try relative to base
        cand = base_dir / filename
        if cand.exists():
            return cand.resolve()

        # 3. Try relative to root parent
        cand = self.root.parent / filename
        if cand.exists():
            return cand.resolve()

        raise FileNotFoundError(filename)
