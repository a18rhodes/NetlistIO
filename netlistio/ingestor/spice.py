"""
Defines SPICE-specific parsing logic and constants.

This module contains all SPICE format-specific parsing heuristics,
including continuation line handling, comment detection, and instance
parsing using the last-positional-token algorithm.
"""

import functools
import mmap
import re
from pathlib import Path
from typing import Iterator

from netlistio.ingestor.parser import ChunkParser, ChunkParserFactory, LineParser
from netlistio.ingestor.scanner import ScanStrategy
from netlistio.models.generic import Instance, Port
from netlistio.models.parsing import IncludeDirective, LibraryDirective, ParseRegion
from netlistio.models.spice import Subckt, get_definition_from_prefix, passive_registry

__all__ = [
    "SpiceScanStrategy",
    "SPICE_COMMENT_CHARS",
    "RE_SUBCKT",
    "RE_ENDS",
]

_SUBCKT = ".SUBCKT"

RE_SUBCKT = re.compile(
    rf"^\s*(?P<delimiter>\{_SUBCKT.lower()})\s+(?P<name>[^\s]+)".encode("utf-8"),
    re.IGNORECASE | re.MULTILINE,
)
RE_ENDS = re.compile(
    rb"^\s*\.ends",
    re.IGNORECASE | re.MULTILINE,
)
RE_LIBRARY = re.compile(
    rb"^\s*\.lib\s+(?P<filename>[^\s]+)(?:\s+(?P<section>[^\s]+))?",
    re.IGNORECASE | re.MULTILINE,
)
RE_INCLUDE = re.compile(
    rb"^\s*\.include\s+(?P<filename>[^\s]+)",
    re.IGNORECASE | re.MULTILINE,
)
RE_CADENCE_STRICT_INCLUDE = re.compile(
    rb'^\s*\[\!\s*(?P<filename>[^"]+)\s*\]',
    re.IGNORECASE | re.MULTILINE,
)
RE_CADENCE_LENIENT_INCLUDE = re.compile(
    rb'^\s*\[\?\s*(?P<filename>[^"]+)\s*\]',
    re.IGNORECASE | re.MULTILINE,
)
SPICE_COMMENT_CHARS = ("*", "$")
SPICE_CONTINUATION_CHAR = "+"


@functools.lru_cache(maxsize=16)
def _passive_registry() -> set[type]:
    """Returns a copy of the SPICE passive primitive registry - cached for performance."""
    return passive_registry()


@functools.lru_cache(maxsize=16)
def _is_passive_primitive(cls: type) -> bool:
    """Checks if a given Primitive class is passive."""
    return cls in _passive_registry()


class SpiceScanStrategy(ScanStrategy):
    """SPICE-specific scanning strategy using regex patterns."""

    def matches_macro_start(self, line: bytes) -> tuple[str, str] | None:
        """Check if line starts a SUBCKT definition."""
        if match := RE_SUBCKT.search(line):
            delimiter = match.group("delimiter").decode("utf-8", errors="ignore")
            name = match.group("name").decode("utf-8", errors="ignore")
            return (delimiter, name)
        return None

    def matches_macro_end(self, line: bytes) -> bool:
        """Check if line is an ENDS directive."""
        return RE_ENDS.match(line) is not None


class SpiceChunkParser(ChunkParser):
    """SPICE-specific chunk parser handling logical lines."""

    def __init__(self, mm, region, line_parser):
        super().__init__(mm, region, line_parser)
        self._title_line_consumed = False

    def _is_comment(self, line: str) -> bool:
        """Check if line is a comment (starts with *, $)."""
        return not line or line[0] in SPICE_COMMENT_CHARS

    def _is_continuation(self, line: str) -> bool:
        """Check if line is a continuation line (starts with +)."""
        return line.startswith("+")

    def _accumulate_logical_line(self, accumulated: list[str]) -> str | None:
        """Join accumulated lines and filter out comments."""
        if not accumulated:
            return None
        logical_line = " ".join(accumulated)
        return None if self._is_comment(logical_line) else logical_line

    def _read_physical_line(self) -> str | None:
        """Read and decode a single physical line from mmap."""
        if self.mm.tell() >= self.region.end_byte:
            return None
        self.current_line_number += 1
        line_bytes = self.mm.readline()
        if not line_bytes:
            return None
        return line_bytes.decode("utf-8", errors="ignore").strip()

    def __iter__(self) -> Iterator[str]:
        """
        Iterate over logical lines in the region.

        Handles SPICE '+' continuation lines by accumulating them into
        single logical lines. Tracks physical line numbers for error reporting.
        Filters out SPICE comments (* $ .). In GLOBAL regions, skips the first
        non-directive line as it's traditionally a SPICE title line.
        """
        self.mm.seek(self.region.start_byte)
        accumulated = []
        line_count = 0
        while True:
            line = self._read_physical_line()
            if line is None:
                break
            line_count += 1
            if self.region.start_byte == 0 and not self._title_line_consumed:
                self._title_line_consumed = True
                continue
            if self._is_comment(line):
                continue
            if self._is_continuation(line):
                accumulated.append(line[1:].strip())
            else:
                yield self._accumulate_logical_line(accumulated)
                accumulated = [line]
        yield self._accumulate_logical_line(accumulated)


class SpiceLineParser(LineParser):
    """SPICE-specific line parser implementing last-positional-token logic."""

    def parse_instance(self, line: str):
        """
        Parses a SPICE instance line using last-positional-token logic.

        :param line: Logical line string.
        :return: Instance object or None if line is not an instance.
        """
        tokens = line.split()
        params = {}
        nets = []
        if len(tokens) < 2:
            return None
        name_probably = tokens.pop(0)
        definition_name = None
        try:
            definition = get_definition_from_prefix(name_probably[0])
        except ValueError:
            return None
        if _is_passive_primitive(definition):
            definition_name = definition.name
            tokens = self._normalize_passive_instance(tokens)
        for token in reversed(tokens):
            if "=" in token:
                key, value = token.split("=", 1)
                params[key] = value
            elif definition_name is None:
                definition_name = token
            else:
                nets.append(token)
        nets = dict.fromkeys(reversed(nets))
        if issubclass(definition, Subckt):
            return Instance(
                name=name_probably,
                nets=nets,
                params=params,
                definition_name=definition_name,
            )
        return Instance(
            name=name_probably,
            nets=nets,
            params=params,
            definition=definition(),
        )

    def _normalize_passive_instance(self, tokens: list[str]) -> str:
        """
        Normalizes primitive instance line by ensuring model name is last token.

        :param line: Logical line string.
        :return: Normalized line string.
        """
        if len(tokens) < 2:
            return tokens
        # For passive devices, the last token is the value, and the
        # model name is implicit based on the instance prefix.
        return [*tokens[:-1], f"value={tokens[-1]}"]

    def parse_declaration(self, line: str):
        """
        Parses a SPICE declaration line.

        :param line: Logical line string.
        :return: Cell object or None if line is not a declaration.
        """
        if RE_SUBCKT.search(line.encode("utf-8")):
            tokens = line.split()
            _, name, *ports = tokens
            return Subckt(name=name, ports=tuple(Port(p) for p in ports))
        return None

    def parse_include(self, line: str):
        """
        Parses a SPICE include line.

        :param line: Logical line string.
        :return: Included filename or None if line is not an include.
        """
        if match := RE_INCLUDE.search(line.encode("utf-8")):
            filename = self._get_filepath_from_match(match)
            return IncludeDirective(filepath=filename, source_file=self.filepath, strict=True)
        if match := RE_LIBRARY.search(line.encode("utf-8")):
            filename = self._get_filepath_from_match(match)
            section = None
            if section_match := match.group("section"):
                section = section_match.decode("utf-8", errors="ignore")
            return LibraryDirective(filepath=filename, source_file=self.filepath, section=section, strict=True)
        if match := RE_CADENCE_STRICT_INCLUDE.search(line.encode("utf-8")):
            filename = self._get_filepath_from_match(match)
            return IncludeDirective(filepath=filename, source_file=self.filepath, strict=True)
        if match := RE_CADENCE_LENIENT_INCLUDE.search(line.encode("utf-8")):
            filename = self._get_filepath_from_match(match)
            return IncludeDirective(filepath=filename, source_file=self.filepath, strict=False)
        return None

    @staticmethod
    def _get_filepath_from_match(match: re.Match[bytes]) -> str:
        """Extracts and decodes filepath from regex match."""
        return match.group("filename").decode("utf-8", errors="ignore").strip("\"'")


class SpiceChunkParserFactory(ChunkParserFactory):
    """
    Factory for creating SPICE-specific ChunkParsers.
    """

    def __call__(self, filepath: str | Path, mm: mmap.mmap, region: ParseRegion) -> ChunkParser:
        """
        Creates a ChunkParser for the given region.
        """
        return SpiceChunkParser(mm, region, SpiceLineParser(filepath, mm, region))
