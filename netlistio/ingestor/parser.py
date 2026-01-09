"""
Defines the parallel parsing engine and abstractions.

Provides the multiprocessing infrastructure for parsing large netlists
using a worker pool. Delegates format-specific line parsing to LineParser
subclasses.
"""

from __future__ import annotations

import abc
import mmap
import multiprocessing
from pathlib import Path
from typing import Iterable, Iterator

from netlistio.ingestor.common import open_mmap
from netlistio.models.generic import Cell, Instance, Macro
from netlistio.models.parsing import (
    IncludeDirective,
    ParseError,
    ParseRegion,
    ParseResult,
)

__all__ = ["ChunkParserFactory", "LineParser", "ChunkParser", "Parser"]


def _worker_entry_point(args: tuple[str, ParseRegion, ChunkParserFactory]) -> ParseResult:
    """
    Worker process entry point for parallel parsing.

    :param args: Tuple of (filepath, region, chunk_parser_factory).
    :return: ParseResult from parsing the region.
    """
    filepath, region, chunk_parser_factory = args
    with open_mmap(filepath) as mm:
        parser = chunk_parser_factory(filepath, mm, region)
        return parser.parse()


class ChunkParserFactory(abc.ABC):
    """
    Abstract factory for creating ChunkParser instances.

    Subclasses provide format-specific ChunkParser construction logic.
    """

    @abc.abstractmethod
    def __call__(self, mm: mmap.mmap, region: ParseRegion) -> ChunkParser:
        """
        Creates a ChunkParser for the given region.

        :param mm: Memory-mapped file object.
        :param region: Parse region to process.
        :return: Format-specific ChunkParser instance.
        """


class LineParser(abc.ABC):
    """
    Abstract base class for format-specific line parsers.

    Subclasses implement format-specific logic for line iteration,
    instance parsing, and declaration parsing.
    """

    def __init__(self, filepath: str | Path, mm: mmap.mmap, region: ParseRegion):
        """
        Initializes line parser with memory-mapped file and region.

        :param mm: Memory-mapped file object.
        :param region: Parse region to process.
        """
        self.mm = mm
        self.region = region
        self.errors: list[ParseError] = []
        self.current_line_number = 0
        self.filepath = filepath

    @abc.abstractmethod
    def parse_instance(self, line: str) -> Instance | None:
        """
        Parses an instance line.

        :param line: Logical line string.
        :return: Instance object or None if line is not an instance.
        """

    @abc.abstractmethod
    def parse_declaration(self, line: str) -> Cell | None:
        """
        Parses a declaration line.

        :param line: Logical line string.
        :return: Cell object or None if line is not a declaration.
        """

    @abc.abstractmethod
    def parse_include(self, line: str) -> IncludeDirective | None:
        """
        Parses an include line.

        :param line: Logical line string.
        :return: Included filename or None if line is not an include.
        """


class ChunkParser:
    """
    Minimal parser that delegates format logic to LineParser.

    Composes with a LineParser to handle format-specific parsing while
    providing a common interface for multiprocessing workers.
    """

    def __init__(self, mm: mmap.mmap, region: ParseRegion, line_parser: LineParser):
        """
        Initializes chunk parser with region and line parser.

        :param mm: Memory-mapped file object.
        :param region: Parse region to process.
        :param line_parser: Format-specific line parser.
        """
        self.current_line_number = 0
        self.mm = mm
        self.region = region
        self.line_parser = line_parser

    @abc.abstractmethod
    def __iter__(self) -> Iterator[str]:
        """
        Iterates over logical lines in the region.

        Handles format-specific line continuation and comment filtering.

        :return: Iterator yielding logical lines as strings.
        """

    def parse(self) -> ParseResult:
        """
        Parses the region and returns cells and errors.

        :return: ParseResult with cells and errors.
        """
        cells = []
        includes = []
        macro: Macro | None = None

        for line in self:
            if not line:
                continue

            # Handle declarations (Subckts, Models)
            if decl := self.line_parser.parse_declaration(line):
                if isinstance(decl, Macro):
                    # It's a container (e.g., .subckt), this region defines it
                    macro = decl
                elif macro:
                    # It's an atomic decl inside a macro (e.g., .model inside .subckt)
                    macro.children.append(decl)
                else:
                    # It's a global atomic decl (e.g., .model at top level)
                    cells.append(decl)

            # Handle Includes
            elif include_info := self.line_parser.parse_include(line):
                includes.append(include_info)

            # Handle Instances
            elif instance := self.line_parser.parse_instance(line):
                if macro:
                    macro.children.append(instance)
                else:
                    cells.append(instance)

        if macro:
            return ParseResult(
                filepath=self.region.filepath, cells=[macro], errors=self.line_parser.errors, includes=includes
            )
        return ParseResult(
            filepath=self.region.filepath, cells=cells, errors=self.line_parser.errors, includes=includes
        )


class Parser:
    """
    High-level parser coordinating scanning and parallel parsing.

    Distributes parse regions across worker processes for high throughput.
    """

    def __init__(
        self,
        filepath: str | Path,
        scanner: Iterable[ParseRegion],
        chunk_parser_factory: ChunkParserFactory,
    ):
        """
        Initializes parser with file, scanner, and factory.

        :param filepath: Path to the netlist file.
        :param scanner: Iterable of ParseRegion objects.
        :param chunk_parser_factory: Factory for creating ChunkParsers.
        """
        self.filepath = Path(filepath)
        self.scanner = scanner
        self.chunk_parser_factory = chunk_parser_factory

    def parse(self, num_workers: int = 4) -> ParseResult:
        """
        Parses the file using multiple worker processes.

        :param num_workers: Number of worker processes to spawn.
        :return: Aggregated ParseResult from all workers.
        """
        work_items = [(str(self.filepath), region, self.chunk_parser_factory) for region in self.scanner]
        all_cells = []
        all_errors = []
        all_includes = set()
        with multiprocessing.Pool(processes=num_workers) as pool:
            for result in pool.imap_unordered(_worker_entry_point, work_items):
                all_cells.extend(result.cells)
                all_errors.extend(result.errors)
                all_includes.update(result.includes)
        return ParseResult(filepath=str(self.filepath), cells=all_cells, errors=all_errors, includes=list(all_includes))
