"""Format-agnostic scanner using composition pattern."""

import abc
import mmap
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from netlistio.ingestor.common import open_mmap
from netlistio.models.parsing import ParseRegion, RegionType

__all__ = ["ScanStrategy", "ScanContext", "Scanner"]


class ScanStrategy(abc.ABC):
    """
    Abstract base for format-specific scanning strategies.

    Subclasses implement format-specific logic for detecting macro
    boundaries (e.g., .SUBCKT/.ENDS in SPICE, module/endmodule in Verilog).
    """

    @abc.abstractmethod
    def matches_macro_start(self, line: bytes) -> tuple[str, str] | None:
        """
        Checks if line starts a macro definition.

        :param line: Raw line bytes from the file.
        :return: Tuple of (delimiter, name) if match, otherwise None.
        """

    @abc.abstractmethod
    def matches_macro_end(self, line: bytes) -> bool:
        """
        Checks if line ends a macro definition.

        :param line: Raw line bytes from the file.
        :return: True if line ends macro scope.
        """


@dataclass(slots=True)
class ScanContext:
    """
    Maintains state for the scanner finite state machine.

    :param scan_strategy: Format-specific scanning logic.
    :param regions: Queue of discovered parse regions.
    :param current_start: Byte offset where current region began.
    :param depth: Nesting depth for nested macro definitions.
    :param context_name: Name of the enclosing macro (if in_macro=True).
    :param context_delimiter: Delimiter that started the macro (e.g., '.SUBCKT').
    :param in_macro: True if currently inside a macro definition.
    """

    scan_strategy: ScanStrategy
    regions: deque = field(default_factory=deque)
    current_start: int = field(default=0)
    depth: int = field(default=0)
    context_name: str | None = None
    context_delimiter: str | None = None
    in_macro: bool = False


class Scanner:
    """
    Format-agnostic scanner that delegates to ScanStrategy.

    Scans netlist files to identify parse regions (GLOBAL vs MACRO scopes)
    using a finite state machine. Supports nested macro definitions.
    """

    def __init__(self, filepath: str | Path, scan_strategy: ScanStrategy):
        """
        Initializes scanner with file path and format strategy.

        :param filepath: Path to the netlist file.
        :param scan_strategy: Format-specific scanning strategy.
        """
        self.filepath = Path(filepath)
        self.context = ScanContext(scan_strategy=scan_strategy)

    def __iter__(self):
        yield from self.scan()

    def _read_line(self, mm: mmap.mmap, start_pos: int) -> tuple[bytes, int, int] | None:
        """
        Reads a single line from the memory-mapped file.

        :param mm: Memory-mapped file object.
        :param start_pos: Current position before reading.
        :return: Tuple of (line_bytes, start_pos, end_pos) or None at EOF.
        """
        line = mm.readline()
        if not line:
            return None
        return (line, start_pos, mm.tell())

    def _handle_global_line(self, line: bytes, cur: int) -> None:
        """
        Processes a line in global scope.

        :param line: Raw line bytes.
        :param cur: Current byte offset.
        """
        if match := self.context.scan_strategy.matches_macro_start(line):
            if cur > self.context.current_start:
                self.context.regions.append(
                    ParseRegion(
                        filepath=str(self.filepath),
                        start_byte=self.context.current_start,
                        end_byte=cur,
                        region_type=RegionType.GLOBAL,
                    )
                )
            delimiter, name = match
            self.context.context_delimiter = delimiter
            self.context.context_name = name
            self.context.current_start = cur
            self.context.depth = 1
            self.context.in_macro = True

    def _handle_macro_line(self, line: bytes, cur: int, nxt: int) -> None:
        """
        Processes a line inside macro scope.

        :param line: Raw line bytes.
        :param cur: Current byte offset (line start).
        :param nxt: Next byte offset (line end).
        """
        if self.context.scan_strategy.matches_macro_start(line):
            self.context.depth += 1
        elif self.context.scan_strategy.matches_macro_end(line):
            self.context.depth -= 1
            if self.context.depth == 0:
                self.context.regions.append(
                    ParseRegion(
                        filepath=str(self.filepath),
                        start_byte=self.context.current_start,
                        end_byte=nxt,
                        region_type=RegionType.MACRO,
                        context_delimiter=self.context.context_delimiter,
                        context_name=self.context.context_name,
                    )
                )
                self.context.current_start = nxt
                self.context.in_macro = False

    def _scan_regions(self, mm: mmap.mmap) -> None:
        """
        Scans file and populates regions using state machine.

        :param mm: Memory-mapped file object.
        """
        start_pos = 0
        while True:
            result = self._read_line(mm, start_pos)
            if result is None:
                break
            line, start_pos, end_pos = result
            if self.context.in_macro:
                self._handle_macro_line(line, start_pos, end_pos)
            else:
                self._handle_global_line(line, start_pos)
            start_pos = end_pos
        self._finalize_region(start_pos)

    def _finalize_region(self, start_pos: int) -> None:
        """
        Finalizes the current region at EOF.

        :param start_pos: Current byte offset at end of file.
        """
        if start_pos > self.context.current_start:
            self.context.regions.append(
                ParseRegion(str(self.filepath), self.context.current_start, start_pos, RegionType.GLOBAL)
            )

    def scan(self) -> deque[ParseRegion]:
        """
        Scans file and returns parse regions.

        :return: Queue of ParseRegion objects representing file structure.
        """
        with open_mmap(self.filepath) as mm:
            self._scan_regions(mm)
        return self.context.regions
