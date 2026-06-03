"""
Defines SPICE-specific parsing logic and constants.

This module contains all SPICE format-specific parsing heuristics.
Crucially, it distinguishes between library *references* (directives)
and library *definitions* (structural markers).
"""

import mmap
import re
from pathlib import Path
from typing import Any, Generator

from netlistio.ingestor.library import LibraryProcessor
from netlistio.ingestor.parser import ChunkParser, ChunkParserFactory, LineParser
from netlistio.ingestor.scanner import ScanStrategy
from netlistio.models.generic import Instance, NetConnection, Port, Primitive
from netlistio.models.parsing import (
    WHOLE_FILE,
    IncludeDirective,
    LibraryDirective,
    ParseRegion,
)
from netlistio.models.spice import (
    MOSFET,
    NMOS,
    PMOS,
    Model,
    Subckt,
    get_definition_from_prefix,
    passive_registry,
)

__all__ = ["SpiceScanStrategy", "SpiceChunkParserFactory", "SpiceLineParser", "SPICE_COMMENT_CHARS"]

SPICE_COMMENT_CHARS = ("*", "$")

# The passive set is fixed once models.spice finishes importing; snapshot it once.
_PASSIVE_TYPES = passive_registry()


class SpiceScanStrategy(ScanStrategy):
    """SPICE-specific scanning strategy."""

    RE_SUBCKT = re.compile(rb"^\s*(?P<delimiter>\.subckt)\s+(?P<name>[^\s]+)", re.IGNORECASE | re.MULTILINE)
    RE_ENDS = re.compile(rb"^\s*\.ends", re.IGNORECASE | re.MULTILINE)

    def matches_macro_start(self, line: bytes) -> tuple[str, str] | None:
        """
        Checks whether *line* opens a SUBCKT definition.

        :param line: Raw line bytes from the file.
        :return: Tuple of (delimiter, name) on match, otherwise None.
        """
        if match := self.RE_SUBCKT.search(line):
            delimiter = match.group("delimiter").decode("utf-8", errors="ignore")
            name = match.group("name").decode("utf-8", errors="ignore")
            return (delimiter, name)
        return None

    def matches_macro_end(self, line: bytes) -> bool:
        """
        Checks whether *line* is an ENDS directive.

        :param line: Raw line bytes from the file.
        :return: True if the line closes a SUBCKT scope.
        """
        return self.RE_ENDS.match(line) is not None


class SpiceChunkParser(ChunkParser):
    """SPICE-specific chunk parser that assembles logical lines from physical ones."""

    COMMENT_CHARS = ("*", "$")
    CONTINUATION_CHAR = "+"

    def __init__(self, mm: mmap.mmap, region: ParseRegion, line_parser: LineParser):
        super().__init__(mm, region, line_parser)
        self._title_line_consumed = False

    def _is_comment(self, line: str) -> bool:
        """
        Returns True if *line* is a SPICE comment.

        A line is a comment if it is empty or starts with ``*`` or ``$``.

        :param line: Decoded, stripped physical line.
        """
        return not line or line[0] in self.COMMENT_CHARS

    def _is_continuation(self, line: str) -> bool:
        """
        Returns True if *line* is a SPICE continuation line (starts with ``+``).

        :param line: Decoded, stripped physical line.
        """
        return line.startswith(self.CONTINUATION_CHAR)

    def _read_physical_line(self) -> str | None:
        """
        Reads and decodes a single physical line from the mmap.

        Respects the region's ``end_byte`` boundary; returns None at EOF or
        when the boundary is exceeded.

        :return: Stripped line string, or None if the region is exhausted.
        """
        if self.mm.tell() >= self.region.end_byte and self.region.end_byte != WHOLE_FILE:
            return None
        self.current_line_number += 1
        line_bytes = self.mm.readline()
        if not line_bytes:
            return None
        return line_bytes.decode("utf-8", errors="ignore").strip()

    def _consume_title_line(self) -> list[str] | None:
        """
        Handles the SPICE title-line convention for GLOBAL regions.

        SPICE requires that the first line of a netlist file be treated as a
        title/comment regardless of its content. This method reads and discards
        that line when processing a region that starts at byte 0.

        :return: Seed accumulator (``[directive]`` if the first line is a
            directive, otherwise ``[]``), or None if the region is empty.
        """
        if self.region.start_byte != 0 or self._title_line_consumed:
            return []
        first_line = self._read_physical_line()
        if first_line is None:
            return None
        if self._is_comment(first_line):
            return []
        if first_line.startswith("."):
            return [first_line]
        self._title_line_consumed = True
        return []

    def __iter__(self) -> Generator[str, Any, Any]:
        """
        Iterates over logical lines in the region.

        Handles SPICE ``+`` continuation lines by accumulating them into
        single logical lines. Filters out SPICE comments (``*``, ``$``). In
        GLOBAL regions, skips the first non-directive line as it is
        traditionally a SPICE title line. Never yields empty strings.
        """
        self.mm.seek(self.region.start_byte)
        accumulated = self._consume_title_line()
        if accumulated is None:
            return
        while (line := self._read_physical_line()) is not None:
            if self._is_comment(line):
                continue
            if self._is_continuation(line):
                accumulated.append(line[1:].strip())
                continue
            if accumulated:
                yield " ".join(accumulated)
            accumulated = [line]
        if accumulated:
            yield " ".join(accumulated)


class SpiceLineParser(LineParser):
    """SPICE-specific line parser."""

    _SUBCKT = ".SUBCKT"
    _RE_EQUALS_NORM = re.compile(r"\s*=\s*")
    _MODEL_PATTERN = r"^\s*(?P<delimiter>\.model)\s+(?P<name>\S+)\s+(?P<type>\S+)\s*(?P<params>.*)$"
    RE_MODEL_STR = re.compile(_MODEL_PATTERN, re.IGNORECASE | re.MULTILINE)
    RE_LIB_DIRECTIVE = re.compile(
        rb"^\s*\.lib\s+(?:[\"'](?P<q_filename>[^\"']+)[\"']|(?P<u_filename>[^\s]+))(?:\s+(?P<section>[^\s]+))?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    RE_INCLUDE = re.compile(
        rb"^\s*\.include\s+(?:[\"'](?P<q_filename>[^\"']+)[\"']|(?P<u_filename>[^\s]+))", re.IGNORECASE | re.MULTILINE
    )
    RE_CADENCE_STRICT = re.compile(rb'^\s*\[\!\s*(?P<filename>[^"\]]+)\s*\]', re.IGNORECASE | re.MULTILINE)
    RE_CADENCE_LENIENT = re.compile(rb'^\s*\[\?\s*(?P<filename>[^"\]]+)\s*\]', re.IGNORECASE | re.MULTILINE)

    def parse_instance(self, line: str) -> Instance | None:
        """
        Parses a SPICE instance line into an Instance model.

        Instance lines are identified by their leading character (the SPICE
        device prefix, e.g. ``R`` for resistor, ``X`` for subcircuit). The
        remainder of the line is parsed as an ordered list of net names
        followed by the model/subcircuit reference, with optional ``key=value``
        parameters interspersed or trailing.

        Parameter extraction works as follows: after stripping key=value tokens,
        the last remaining token is treated as the model/definition name and
        everything before it is treated as net connections in order. For passive
        devices (R, C, L), the parser additionally checks whether the *last*
        token is a bare numeric value and, if so, moves it to ``params["value"]``
        before the model-name extraction step runs.

        :param line: Logical line string (continuation-joined, comment-stripped).
        :return: Instance on success, None if the line is not a valid instance.
        """
        name_token, tokens = self._split_instance_line(line)
        if name_token is None:
            return None
        if (definition_cls := self._classify_prefix(name_token)) is None:
            return None
        nets_list, params, definition_name = self._parse_device_tokens(tokens, definition_cls)
        return self._build_instance(name_token, definition_cls, nets_list, params, definition_name)

    def _split_instance_line(self, line: str) -> tuple[str | None, list[str]]:
        """
        Normalises ``=`` spacing and splits the line into (name_token, rest).

        Returns ``(None, [])`` when the line has fewer than two tokens, which
        means it cannot be a valid instance line.

        :param line: Raw logical line.
        :return: Tuple of (name_token, remaining_tokens) or (None, []).
        """
        tokens = self._RE_EQUALS_NORM.sub("=", line).split()
        if len(tokens) < 2:
            return None, []
        return tokens[0], tokens[1:]

    def _classify_prefix(self, name_token: str) -> type | None:
        """
        Maps the leading character of an instance name to a definition class.

        :param name_token: The full instance name (e.g. ``R1``, ``Xbuf``).
        :return: The definition class, or None if the prefix is unrecognised.
        """
        try:
            return get_definition_from_prefix(name_token[0])
        except ValueError:
            return None

    def _parse_device_tokens(
        self, tokens: list[str], definition_cls: type
    ) -> tuple[list[NetConnection], dict, str | None]:
        """
        Extracts nets, params, and the definition name from the token list.

        Mutates *tokens* in place: key=value pairs are removed and (for passives)
        a trailing numeric value token is also removed. What remains after both
        extractions is the net-and-model token sequence.

        :param tokens: Mutable token list (everything after the instance name).
        :param definition_cls: Device class resolved from the instance prefix.
        :return: Tuple of (nets_list, params, definition_name).
        """
        params: dict[str, str] = {}
        definition_name = self._handle_passive_prefix(tokens, definition_cls, params)
        self._extract_params(tokens, params)
        nets_list, definition_name = self._separate_nets_from_model(tokens, definition_name)
        return nets_list, params, definition_name

    def _handle_passive_prefix(self, tokens: list[str], definition_cls: type, params: dict[str, str]) -> str | None:
        """
        Handles passive-device (R, C, L) token conventions.

        For passives, the definition name is the device class name (e.g.
        "resistor") rather than a model reference. A trailing bare numeric
        value token (e.g. ``10k``) is moved into ``params["value"]``.

        :param tokens: Mutable token list; trailing value token may be popped.
        :param definition_cls: Device class for the current instance.
        :param params: Params dict to populate if a value token is found.
        :return: Definition name string for passives, None otherwise.
        """
        if definition_cls not in _PASSIVE_TYPES:
            return None
        if tokens and self._is_value(tokens[-1]):
            params["value"] = tokens.pop()
        return definition_cls.name

    def _separate_nets_from_model(
        self, tokens: list[str], definition_name: str | None
    ) -> tuple[list[NetConnection], str | None]:
        """
        Partitions remaining tokens into net names and the model/subckt reference.

        Iterates from the end: the last token not yet assigned to
        *definition_name* becomes the model reference; all preceding tokens
        are net connections (restored to forward order).

        Duplicate net names are preserved — two terminals tied to the same net
        (e.g. source and bulk both on vss) produce two separate entries so that
        positional port assignment in the linker remains correct.

        :param tokens: Tokens remaining after param and passive-value extraction.
        :param definition_name: Pre-assigned definition name (passives only).
        :return: Tuple of (nets_list, definition_name).
        """
        nets: list[str] = []
        for token in reversed(tokens):
            if definition_name is None:
                definition_name = token
            else:
                nets.append(token)
        nets.reverse()
        return [NetConnection(n) for n in nets], definition_name

    def _build_instance(
        self,
        name_token: str,
        definition_cls: type,
        nets_list: list[tuple[str, None]],
        params: dict,
        definition_name: str | None,
    ) -> Instance:
        """
        Assembles the final Instance, handling Subckt vs Primitive distinction.

        Subckts carry an unresolved ``definition_name`` for the linker to
        resolve; primitives are instantiated directly (with MOSFET refinement
        applied when possible).

        :param name_token: Full instance name string (e.g. ``M1``).
        :param definition_cls: Device class resolved from the prefix.
        :param nets_list: Ordered list of NetConnection objects; ports filled by linker.
        :param params: Parsed key=value parameters.
        :param definition_name: Model or subcircuit reference name.
        :return: Populated Instance.
        """
        if issubclass(definition_cls, Subckt) or getattr(definition_cls, "inst_prefix", None) == "X":
            return Instance(name=name_token, nets=nets_list, params=params, definition_name=definition_name)
        definition = self._resolve_primitive(definition_cls, definition_name)
        return Instance(name=name_token, nets=nets_list, params=params, definition=definition)

    def _resolve_primitive(self, definition_cls: type, definition_name: str | None) -> Primitive:
        """
        Instantiates a primitive, applying the NMOS/PMOS heuristic for MOSFETs.

        :param definition_cls: The primitive class.
        :param definition_name: Model name string for heuristic refinement.
        :return: Instantiated primitive.
        """
        if definition_name and issubclass(definition_cls, MOSFET):
            return self._classify_mosfet(definition_name)
        return definition_cls()  # pylint: disable=no-value-for-parameter

    def _classify_mosfet(self, model_name: str) -> MOSFET:
        """
        Refines a generic MOSFET to NMOS or PMOS from the model name string.

        Checks known substrings first (``nmos``, ``nfet``, ``pmos``, ``pfet``),
        then falls back to the first character (``n``/``p``). This heuristic
        runs before linking; the linker may later resolve a more specific type
        from a ``.model`` directive.

        :param model_name: Model reference string from the instance line.
        :return: NMOS, PMOS, or MOSFET instance.
        """
        name_lower = model_name.lower()
        if any(kw in name_lower for kw in ("nmos", "nfet")) or name_lower.startswith("n"):
            return NMOS()  # pylint: disable=no-value-for-parameter
        if any(kw in name_lower for kw in ("pmos", "pfet")) or name_lower.startswith("p"):
            return PMOS()  # pylint: disable=no-value-for-parameter
        return MOSFET()  # pylint: disable=no-value-for-parameter

    def _extract_params(self, tokens: list[str], params: dict[str, str]) -> None:
        """
        Extracts ``key=value`` tokens from *tokens* into *params* in place.

        Iterates the token list backwards so indices remain valid as items are
        removed. Tokens without ``=`` are left untouched and remain as net names
        or the model reference for the caller to handle.

        :param tokens: Mutable token list; matched pairs are removed.
        :param params: Params dict to populate.
        """
        i = len(tokens) - 1
        while i >= 0:
            if "=" in (token := tokens[i]):
                k, v = token.split("=", 1)
                params[k] = v
                tokens.pop(i)
            i -= 1

    def _is_value(self, token: str) -> bool:
        """
        Returns True if *token* looks like a bare numeric value (e.g. ``10k``, ``1.5e-9``).

        Used to detect the optional trailing value token on passive device lines.

        :param token: Single token string.
        """
        if not token:
            return False
        c = token[0]
        return c.isdigit() or c in (".", "-", "+")

    def parse_declaration(self, line: str):
        """
        Parses a SPICE declaration line (.SUBCKT or .MODEL).

        :param line: Logical line string.
        :return: Subckt, Model, or None if the line is neither.
        """
        if line.lstrip().upper().startswith(self._SUBCKT):
            return self._parse_subckt(line)
        if match := self.RE_MODEL_STR.search(line):
            return self._parse_model(match)
        return None

    def _parse_subckt(self, line: str) -> Subckt | None:
        """
        Parses a .SUBCKT declaration into a Subckt model.

        Port names are extracted from the tokens following the subcircuit name,
        excluding any tokens that contain ``=`` (which are parameter defaults).

        :param line: Logical line beginning with ``.SUBCKT``.
        :return: Subckt instance, or None if the line is malformed.
        """
        tokens = line.split()
        if len(tokens) < 2:
            return None
        _, name, *port_tokens = tokens
        ports = [p for p in port_tokens if "=" not in p]
        return Subckt(name=name, ports=tuple(Port(p) for p in ports))

    def _parse_model(self, match: re.Match) -> Model:
        """
        Parses a .MODEL declaration into a Model.

        :param match: Regex match from RE_MODEL_STR against the line.
        :return: Populated Model instance.
        """
        return Model(
            name=match.group("name"),
            base_type=match.group("type"),
            params=self._parse_model_params(match.group("params")),
        )

    def _parse_model_params(self, params_str: str) -> dict[str, str]:
        """
        Parses the parameter substring of a .MODEL line into a dict.

        Normalises ``=`` spacing, then splits on whitespace. Tokens without
        ``=`` are treated as boolean flags and stored as ``{token: "true"}``.

        :param params_str: Raw parameter substring from the .MODEL line.
        :return: Parsed parameter dict.
        """
        if not params_str:
            return {}
        params: dict[str, str] = {}
        for token in self._RE_EQUALS_NORM.sub("=", params_str).split():
            if "=" in token:
                k, v = token.split("=", 1)
                params[k] = v
            else:
                params[token] = "true"
        return params

    def parse_include(self, line: str):
        """
        Parses a SPICE include/lib directive into an IncludeDirective or LibraryDirective.

        Handles four syntactic variants:
        - ``.include <path>`` — standard include
        - ``.lib <path> [section]`` — library reference with optional section
        - ``[! <path>]`` — Cadence strict include (raises error if missing)
        - ``[? <path>]`` — Cadence lenient include (silently skipped if missing)

        :param line: Logical line string.
        :return: IncludeDirective, LibraryDirective, or None.
        """
        encoded = line.encode("utf-8")
        if match := self.RE_INCLUDE.search(encoded):
            return IncludeDirective(filepath=self._extract_filename(match), source_file=self.filepath)
        if match := self.RE_LIB_DIRECTIVE.search(encoded):
            section = self._decode_group(match, "section")
            return LibraryDirective(filepath=self._extract_filename(match), source_file=self.filepath, section=section)
        if match := self.RE_CADENCE_STRICT.search(encoded):
            return IncludeDirective(
                filepath=self._get_filepath_from_match(match), source_file=self.filepath, strict=True
            )
        if match := self.RE_CADENCE_LENIENT.search(encoded):
            return IncludeDirective(
                filepath=self._get_filepath_from_match(match), source_file=self.filepath, strict=False
            )
        return None

    def _extract_filename(self, match: re.Match[bytes]) -> str:
        """
        Extracts the filename from either the quoted or unquoted capture group.

        :param match: Regex match containing ``q_filename`` or ``u_filename`` groups.
        :return: Decoded filename string.
        """
        if q := match.group("q_filename") if "q_filename" in match.groupdict() else None:
            return q.decode("utf-8", errors="ignore")
        if u := match.group("u_filename") if "u_filename" in match.groupdict() else None:
            return u.decode("utf-8", errors="ignore")
        return self._get_filepath_from_match(match)  # pragma: no cover

    @staticmethod
    def _decode_group(match: re.Match[bytes], group: str) -> str | None:
        """
        Decodes an optional named group from a bytes regex match.

        :param match: Regex match object.
        :param group: Name of the capture group.
        :return: Decoded string, or None if the group did not participate.
        """
        raw = match.group(group)
        return raw.decode("utf-8", errors="ignore") if raw else None

    @staticmethod
    def _get_filepath_from_match(match: re.Match[bytes]) -> str:
        """
        Decodes and strips quotes from the ``filename`` capture group.

        :param match: Regex match containing a ``filename`` group.
        :return: Cleaned filename string.
        """
        return match.group("filename").decode("utf-8", errors="ignore").strip("\"'")


class SpiceChunkParserFactory(ChunkParserFactory):
    """Factory for creating SPICE-specific ChunkParsers."""

    def __call__(self, filepath: str | Path, mm: mmap.mmap, region: ParseRegion) -> ChunkParser:
        """
        Creates a SpiceChunkParser for the given region.

        :param filepath: Path to the file being parsed.
        :param mm: Memory-mapped file object.
        :param region: Parse region to process.
        :return: Configured SpiceChunkParser.
        """
        return SpiceChunkParser(mm, region, SpiceLineParser(filepath, mm, region))


class SpiceLibraryProcessor(LibraryProcessor):
    """SPICE-specific library processor that identifies .lib/.endl section boundaries."""

    SECTION_START = re.compile(rb"^\s*\.lib\s+(?P<section>\w+)", re.IGNORECASE | re.MULTILINE)
    SECTION_END = re.compile(rb"^\s*\.endl(?:\s+(?P<section>\w+))?", re.IGNORECASE | re.MULTILINE)

    def find_start_indicator(self, line):
        """
        Returns an iterator over all ``.lib`` section start matches.

        :param line: Raw mmap bytes to search.
        :return: Iterator of regex Match objects.
        """
        return self.SECTION_START.finditer(line)

    def find_end_indicator(self, line):
        """
        Returns the first ``.endl`` match, or None if absent.

        :param line: Raw mmap bytes to search.
        :return: Regex Match or None.
        """
        return self.SECTION_END.search(line)
