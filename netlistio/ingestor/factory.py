"""
Factory functions for creating parsers and scanners.

Provides high-level factory methods to wire together format-specific
components into complete parser instances for different netlist formats.
"""

import mmap
import os
from pathlib import Path

from netlistio.ingestor.linker import link
from netlistio.ingestor.parser import ChunkParser, ChunkParserFactory, Parser
from netlistio.ingestor.scanner import Scanner
from netlistio.ingestor.spice import SpiceLineParser, SpiceScanStrategy
from netlistio.models import NetlistFormat, ParseRegion
from netlistio.models.linking import Netlist

__all__ = ["get_chunk_parser_factory", "get_parser", "get_scanner", "get_netlist"]


class _SpiceChunkParserFactory(ChunkParserFactory):
    """SPICE-specific chunk parser factory."""

    def __call__(self, mm: mmap.mmap, region: ParseRegion) -> ChunkParser:
        """
        Creates a ChunkParser for SPICE format.

        :param mm: Memory-mapped file object.
        :param region: Parse region to process.
        :return: ChunkParser configured with SpiceLineParser.
        """
        line_parser = SpiceLineParser(mm, region)
        return ChunkParser(mm, region, line_parser)


def get_chunk_parser_factory(netlist_format: NetlistFormat) -> ChunkParserFactory:
    """
    Creates a chunk parser factory for the specified format.

    :param netlist_format: Target netlist format.
    :return: Format-specific ChunkParserFactory.
    :raises ValueError: If format is unsupported.
    """
    match netlist_format:
        case NetlistFormat.SPICE:
            return _SpiceChunkParserFactory()
        case _:
            raise ValueError(f"Unsupported netlist format: {netlist_format}")


def get_parser(filepath: str | Path, netlist_format: NetlistFormat) -> Parser:
    """
    Creates a parser for the specified netlist format.

    :param filepath: Path to the netlist file.
    :param netlist_format: Target netlist format.
    :return: Configured Parser instance.
    :raises ValueError: If format is unsupported.
    """
    return Parser(
        filepath,
        get_scanner(filepath, netlist_format),
        get_chunk_parser_factory(netlist_format),
    )


def get_scanner(filepath: str | Path, netlist_format: NetlistFormat) -> Scanner:
    """
    Creates a scanner for the specified netlist format.

    :param filepath: Path to the netlist file.
    :param netlist_format: Target netlist format.
    :return: Configured Scanner instance.
    :raises ValueError: If format is unsupported.
    """
    filepath = Path(filepath)
    match netlist_format:
        case NetlistFormat.SPICE:
            return Scanner(filepath, SpiceScanStrategy())
        case _:
            raise ValueError(f"Unsupported netlist format: {netlist_format}")


def get_netlist(filepath: str | Path, netlist_format: NetlistFormat, num_workers: int | None = None) -> Netlist:
    """
    Parse and link a netlist file with include resolution.

    :param filepath: Path to the netlist file.
    :param netlist_format: Format of the netlist.
    :param num_workers: Number of worker processes (defaults to CPU count).
    :return: Linked netlist with all includes resolved.
    """
    from .includes import IncludeResolver
    from .library import LibraryProcessor
    from .registry import ModelRegistry

    num_workers = num_workers or os.cpu_count() or 1
    root_path = Path(filepath)

    # Step 1: Resolve all include dependencies
    scanner = get_scanner(root_path, netlist_format)
    include_resolver = IncludeResolver(scanner.context.scan_strategy)
    all_files, library_directives = include_resolver.resolve_includes(root_path)

    # Step 2: Process library files
    library_processor = LibraryProcessor()
    model_registry = ModelRegistry()

    # Setup format-specific model resolver
    if netlist_format == NetlistFormat.SPICE:
        from .spice_resolver import SpiceModelResolver

        model_registry.model_resolver = SpiceModelResolver()

    for lib_directive in library_directives:
        lib_path = Path(lib_directive.filepath)
        try:
            lib_content = library_processor.extract_section(lib_path, lib_directive.section)
            model_registry.register_library_content(str(lib_path), lib_content)
        except ValueError as e:
            # Missing section - halt as requested
            raise ValueError(f"Library processing failed: {e}") from e

    # Step 3: Parse all files (main + includes)
    # For now, just parse the main file - full multi-file parsing is next iteration
    parser = get_parser(root_path, netlist_format)
    parse_result = parser.parse(num_workers=num_workers)

    # Step 4: Enhanced linking with dynamic model registry
    link_result = link(parse_result, model_registry=model_registry)

    for error in link_result.errors:
        print(error)
    return link_result.netlist
