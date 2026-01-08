"""
Library file processing and section boundary extraction.

Handles .lib files with section extraction capabilities for
process corners (tt, ff, ss, etc.) and model definitions.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from netlistio.ingestor.common import open_mmap

__all__ = ["LibraryProcessor", "LibrarySection"]


@dataclass(slots=True, frozen=True)
class LibrarySection:
    """Represents an extracted library section."""

    name: str
    start_byte: int
    end_byte: int


class LibraryProcessor:
    """
    Scans library files to identify the byte boundaries of sections.
    """

    SECTION_START = re.compile(rb"^\s*\.lib\s+(?P<section>\w+)", re.IGNORECASE | re.MULTILINE)
    SECTION_END = re.compile(rb"^\s*\.endl(?:\s+(?P<section>\w+))?", re.IGNORECASE | re.MULTILINE)

    def find_section(self, lib_path: Path, section_name: str) -> LibrarySection:
        """
        Locates the byte range of a specific section in a library file.

        :param lib_path: Path to the library file.
        :param section_name: Name of the section to find.
        :return: LibrarySection containing start/end offsets.
        :raises ValueError: If section is not found.
        """
        with open_mmap(lib_path) as mm:
            # 1. Find Start
            start_offset = -1
            for match in self.SECTION_START.finditer(mm):
                found_name = match.group("section").decode("utf-8", errors="ignore")
                if found_name.lower() == section_name.lower():
                    # We start parsing AFTER the .lib line to avoid
                    # the parser re-identifying it as a directive.
                    start_offset = match.end()
                    break
            if start_offset == -1:
                raise ValueError(f"Section '{section_name}' not found in {lib_path}")
            # 2. Find End
            # We search from the start_offset
            mm.seek(start_offset)
            rest_of_file = mm.read()
            # Simple search for the next .endl
            # Note: A robust implementation would track nesting.
            end_match = self.SECTION_END.search(rest_of_file)
            if end_match:
                end_offset = start_offset + end_match.start()
            else:
                # If no .endl, assume section goes to EOF
                end_offset = mm.size()
            return LibrarySection(section_name, start_offset, end_offset)
