"""
Library file processing and section boundary extraction.

Handles .lib files with section extraction capabilities for
process corners (tt, ff, ss, etc.) and model definitions.
"""

import abc
import re
from mmap import mmap
from pathlib import Path
from typing import Iterator

from netlistio.ingestor.common import open_mmap
from netlistio.models.parsing import LibrarySection

__all__ = ["LibraryProcessor", "LibrarySection"]


class LibraryProcessor(abc.ABC):
    """
    Scans library files to identify the byte boundaries of sections.
    """

    @abc.abstractmethod
    def find_start_indicator(self, line: mmap) -> Iterator[re.Match[str]]:
        """Find the start of a library section"""

    @abc.abstractmethod
    def find_end_indicator(self, line: mmap) -> re.Match[str]:
        """Find the end of a library section"""

    def find_section(self, lib_path: Path, section_name: str) -> LibrarySection:
        """
        Locates the byte range of a specific section in a library file.

        :param lib_path: Path to the library file.
        :param section_name: Name of the section to find.
        :return: LibrarySection containing start/end offsets.
        :raises ValueError: If section is not found.
        """
        with open_mmap(lib_path) as mm:
            start_offset = self._find_start(mm=mm, section_name=section_name)
            if start_offset == -1:
                raise ValueError(f"Section '{section_name}' not found in {lib_path}")
            end_offset = self._find_end(mm=mm, start_offset=start_offset)
            return LibrarySection(section_name, start_offset, end_offset)

    def _find_start(self, mm, section_name: str):
        start_offset = -1
        for match in self.find_start_indicator(mm):
            found_name = match.group("section").decode("utf-8", errors="ignore")
            if found_name.lower() == section_name.lower():
                # We start parsing AFTER the .lib line to avoid
                # the parser re-identifying it as a directive.
                start_offset = match.end()
                break
        return start_offset

    def _find_end(self, mm, start_offset: int):
        mm.seek(start_offset)
        rest_of_file = mm.read()
        end_match = self.find_end_indicator(rest_of_file)
        if end_match:
            end_offset = start_offset + end_match.start()
        else:
            end_offset = mm.size()
        return end_offset
