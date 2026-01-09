"""
Defines SPICE-specific parsing logic and constants.

This module contains all SPICE format-specific parsing heuristics.
Crucially, it distinguishes between library *references* (directives)
and library *definitions* (structural markers).
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
from netlistio.models.spice import (
    Model,
    Subckt,
    get_definition_from_prefix,
    passive_registry,
)

__all__ = [
    "SpiceScanStrategy",
    "SpiceChunkParserFactory",
    "SpiceLineParser",
    "SPICE_COMMENT_CHARS",
]

_SUBCKT = ".SUBCKT"
_MODEL = ".MODEL"

RE_SUBCKT = re.compile(
    rf"^\s*(?P<delimiter>\{_SUBCKT.lower()})\s+(?P<name>[^\s]+)".encode("utf-8"),
    re.IGNORECASE | re.MULTILINE,
)
RE_MODEL = re.compile(
    rf"^\s*(?P<delimiter>\{_MODEL.lower()})\s+(?P<name>\S+)\s+(?P<type>\S+)\s*(?P<params>.*)$".encode("utf-8"),
    re.IGNORECASE | re.MULTILINE,
)
RE_ENDS = re.compile(
    rb"^\s*\.ends",
    re.IGNORECASE | re.MULTILINE,
)
RE_LIB_DIRECTIVE = re.compile(
    rb"^\s*\.lib\s+(?:[\"'](?P<q_filename>[^\"']+)[\"']|(?P<u_filename>[^\s]+))(?:\s+(?P<section>[^\s]+))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
RE_INCLUDE = re.compile(
    rb"^\s*\.include\s+(?:[\"'](?P<q_filename>[^\"']+)[\"']|(?P<u_filename>[^\s]+))",
    re.IGNORECASE | re.MULTILINE,
)
RE_CADENCE_STRICT_INCLUDE = re.compile(
    rb'^\s*\[\!\s*(?P<filename>[^"\]]+)\s*\]',
    re.IGNORECASE | re.MULTILINE,
)
RE_CADENCE_LENIENT_INCLUDE = re.compile(
    rb'^\s*\[\?\s*(?P<filename>[^"\]]+)\s*\]',
    re.IGNORECASE | re.MULTILINE,
)
SPICE_COMMENT_CHARS = ("*", "$")
SPICE_CONTINUATION_CHAR = "+"
_RE_EQUALS_NORM = re.compile(r"\s*=\s*")


@functools.lru_cache(maxsize=16)
def _passive_registry() -> set[type]:
    """Returns a copy of the SPICE passive primitive registry - cached for performance."""
    return passive_registry()


@functools.lru_cache(maxsize=16)
def _is_passive_primitive(cls: type) -> bool:
    """Checks if a given Primitive class is passive."""
    return cls in _passive_registry()


class SpiceScanStrategy(ScanStrategy):
    """SPICE-specific scanning strategy."""

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

    def __init__(self, mm: mmap.mmap, region: ParseRegion, line_parser: LineParser):
        super().__init__(mm, region, line_parser)
        self._title_line_consumed = False

    def _is_comment(self, line: str) -> bool:
        """Check if line is a comment (starts with *, $)."""
        return not line or line[0] in SPICE_COMMENT_CHARS

    def _is_continuation(self, line: str) -> bool:
        """Check if line is a continuation line (starts with +)."""
        return line.startswith(SPICE_CONTINUATION_CHAR)

    def _accumulate_logical_line(self, accumulated: list[str]) -> str | None:
        """Join accumulated lines and filter out comments."""
        if not accumulated:
            return None
        logical_line = " ".join(accumulated)
        if self._is_comment(logical_line):
            return None
        return logical_line

    def _read_physical_line(self) -> str | None:
        """Read and decode a single physical line from mmap."""
        if self.mm.tell() >= self.region.end_byte and self.region.end_byte != -1:
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

        # In GLOBAL regions (start_byte=0), SPICE defines the first line as a Title.
        # We skip it unless it's a directive.
        if self.region.start_byte == 0 and not self._title_line_consumed:
            first_line = self._read_physical_line()
            if first_line and not (self._is_comment(first_line) or first_line.startswith(".")):
                self._title_line_consumed = True
            elif first_line:
                # If it looked like a command, put it back (conceptually) or process it.
                # For simplicity, we just yield it if it's not a comment.
                if not self._is_comment(first_line):
                    accumulated = [first_line]
            else:
                return  # Empty file

        while True:
            line = self._read_physical_line()
            if line is None:
                break

            if self._is_comment(line):
                continue
            if self._is_continuation(line):
                accumulated.append(line[1:].strip())
            else:
                yield self._accumulate_logical_line(accumulated)
                accumulated = [line]
        yield self._accumulate_logical_line(accumulated)


class SpiceLineParser(LineParser):
    """SPICE-specific line parser."""

    def parse_instance(self, line: str):
        line = _RE_EQUALS_NORM.sub("=", line)
        tokens = line.split()
        if len(tokens) < 2:
            return None
        name_token = tokens.pop(0)
        # Quick check: Is it an instance?
        try:
            definition_cls = get_definition_from_prefix(name_token[0])
        except ValueError:
            return None

        # Parse params and nets
        params = {}
        nets = []
        definition_name = None

        # Passive handling (R, C, L often have value as last token)
        if _is_passive_primitive(definition_cls):
            definition_name = definition_cls.name
            # If the last token is a value (digits), move it to params
            if tokens and self._is_value(tokens[-1]):
                params["value"] = tokens.pop()

        # Use helper to extract key=value params
        self._extract_params(tokens, params)

        # Remaining tokens are nets or model name
        for token in reversed(tokens):
            if definition_name is None:
                # The last non-param token is the Model/Subckt Name
                definition_name = token
            else:
                # Everything else is a net
                nets.append(token)

        # Nets were collected in reverse
        nets.reverse()
        # Map nets list to dictionary (keys only)
        nets_dict = dict.fromkeys(nets)

        if issubclass(definition_cls, Subckt):
            return Instance(
                name=name_token,
                nets=nets_dict,
                params=params,
                definition_name=definition_name,
            )
        return Instance(
            name=name_token,
            nets=nets_dict,
            params=params,
            definition=definition_cls(),  # Primitive instance
        )

    def _extract_params(self, tokens: list[str], params: dict[str, str]) -> None:
        """
        Extract key=value parameters from a list of tokens in-place.
        Modified tokens list will have params removed.
        """
        # Iterate backwards to safely pop
        i = len(tokens) - 1
        while i >= 0:
            token = tokens[i]
            if "=" in token:
                k, v = token.split("=", 1)
                params[k] = v
                tokens.pop(i)
            i -= 1

    def _is_value(self, token: str) -> bool:
        """Simple check if token is numeric."""
        if not token:
            return False
        c = token[0]
        return c.isdigit() or c in (".", "-", "+")

    def parse_declaration(self, line: str):
        """
        Parses a SPICE declaration line.

        :param line: Logical line string.
        :return: Cell object or None if line is not a declaration.
        """
        line_bytes = line.encode("utf-8")

        # Check for .SUBCKT
        if RE_SUBCKT.search(line_bytes):
            tokens = line.split()
            if len(tokens) >= 2:
                _, name, *ports = tokens
                # Filter out params from ports list
                ports = [p for p in ports if "=" not in p]
                return Subckt(name=name, ports=tuple(Port(p) for p in ports))

        # Check for .MODEL
        if match := RE_MODEL.search(line_bytes):
            name = match.group("name").decode("utf-8", errors="ignore")
            base_type = match.group("type").decode("utf-8", errors="ignore")
            params_str = match.group("params").decode("utf-8", errors="ignore")

            # Parse parameters string
            params = {}
            if params_str:
                # Normalize = spaces and split
                cleaned_params = _RE_EQUALS_NORM.sub("=", params_str)
                for token in cleaned_params.split():
                    if "=" in token:
                        k, v = token.split("=", 1)
                        params[k] = v
                    else:
                         # Handle valueless flags or errors gracefully
                        params[token] = "true"

            return Model(name=name, base_type=base_type, params=params)

        return None

    def parse_include(self, line: str):
        """
        Parses a SPICE include line.

        :param line: Logical line string.
        :return: Included filename or None if line is not an include.
        """
        encoded = line.encode("utf-8")
        if match := RE_INCLUDE.search(encoded):
            filename = self._extract_filename(match)
            return IncludeDirective(filepath=filename, source_file=self.filepath)
        if match := RE_LIB_DIRECTIVE.search(encoded):
            filename = self._extract_filename(match)
            section_bytes = match.group("section")
            section = section_bytes.decode("utf-8", errors="ignore") if section_bytes else None
            return LibraryDirective(filepath=filename, source_file=self.filepath, section=section)
        if match := RE_CADENCE_STRICT_INCLUDE.search(encoded):
            filename = self._get_filepath_from_match(match)
            return IncludeDirective(filepath=filename, source_file=self.filepath, strict=True)
        if match := RE_CADENCE_LENIENT_INCLUDE.search(encoded):
            filename = self._get_filepath_from_match(match)
            return IncludeDirective(filepath=filename, source_file=self.filepath, strict=False)
        return None

    def _extract_filename(self, match: re.Match[bytes]) -> str:
        """Helper to extract filename from either quoted or unquoted groups."""
        if "q_filename" in match.groupdict() and match.group("q_filename"):
            return match.group("q_filename").decode("utf-8", errors="ignore")
        if "u_filename" in match.groupdict() and match.group("u_filename"):
            return match.group("u_filename").decode("utf-8", errors="ignore")
        return self._get_filepath_from_match(match)

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
