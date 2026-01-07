"""
Library file processing and section extraction.

Handles .lib files with section extraction capabilities for
process corners (tt, ff, ss, etc.) and model definitions.
"""

import mmap
import re
from dataclasses import dataclass
from pathlib import Path

from netlistio.ingestor.common import open_mmap

__all__ = ["LibraryProcessor", "LibrarySection"]


@dataclass(slots=True, frozen=True)
class LibrarySection:
    """Represents an extracted library section."""

    name: str
    content: bytes
    start_byte: int
    end_byte: int


class LibraryProcessor:
    """
    Processes library files and extracts specific sections.

    Handles SPICE library files with section markers like:
    .lib tt
    ... model definitions ...
    .endl tt

    Also recursively processes .include directives within library content.
    """

    # Pattern to match library section starts/ends
    SECTION_START = re.compile(rb"^\s*\.lib\s+(?P<section>\w+)", re.IGNORECASE | re.MULTILINE)
    SECTION_END = re.compile(rb"^\s*\.endl(?:\s+(?P<section>\w+))?", re.IGNORECASE | re.MULTILINE)

    # Pattern to match include directives
    INCLUDE_PATTERN = re.compile(rb"^\s*\.include\s+(?P<filename>[^\s]+)", re.IGNORECASE | re.MULTILINE)

    def __init__(self):
        """Initialize with empty cache for processed files."""
        self._file_cache: dict[str, bytes] = {}

    def extract_section(self, lib_path: Path, section_name: str | None) -> bytes:
        """
        Extract specific section from library file with recursive include processing.

        :param lib_path: Path to library file.
        :param section_name: Name of section to extract (None for entire file).
        :return: Raw bytes of the section content with includes resolved.
        :raises ValueError: If section not found.
        """
        if section_name is None:
            # Return entire file with includes resolved if no section specified
            return self._resolve_includes(lib_path, lib_path.read_bytes())

        with open_mmap(lib_path) as mm:
            section = self._find_section(mm, section_name)
            if section is None:
                raise ValueError(f"Library section '{section_name}' not found in {lib_path}")

            # Recursively resolve includes in the section content
            return self._resolve_includes(lib_path, section.content)

    def _find_section(self, mm: mmap.mmap, section_name: str) -> LibrarySection | None:
        """Find and extract a named section from memory-mapped library file."""
        mm.seek(0)
        content = mm.read()

        # Find section start
        section_start = None
        for match in self.SECTION_START.finditer(content):
            if match.group("section").decode().lower() == section_name.lower():
                section_start = match.end()
                break

        if section_start is None:
            return None

        # Find corresponding section end
        remaining_content = content[section_start:]
        end_match = self.SECTION_END.search(remaining_content)

        if end_match:
            section_end = section_start + end_match.start()
        else:
            # Section goes to end of file
            section_end = len(content)

        section_content = content[section_start:section_end]

        return LibrarySection(
            name=section_name, content=section_content, start_byte=section_start, end_byte=section_end
        )

    def list_sections(self, lib_path: Path) -> list[str]:
        """
        List all available sections in a library file.

        :param lib_path: Path to library file.
        :return: List of section names found in the file.
        """
        with open_mmap(lib_path) as mm:
            content = mm.read()
            sections = []

            for match in self.SECTION_START.finditer(content):
                section_name = match.group("section").decode()
                if section_name not in sections:
                    sections.append(section_name)

            return sections

    def _resolve_includes(self, base_path: Path, content: bytes) -> bytes:
        """
        Recursively resolve .include directives in library content.

        :param base_path: Base path for resolving relative includes.
        :param content: Content to process for includes.
        :return: Content with all includes expanded.
        """
        base_dir = base_path.parent
        result_parts = []
        last_pos = 0

        for match in self.INCLUDE_PATTERN.finditer(content):
            # Add content before the include directive
            result_parts.append(content[last_pos : match.start()])

            # Process the include
            filename = match.group("filename").decode("utf-8", errors="ignore").strip("\"'")
            try:
                include_content = self._load_include_file(base_dir, filename)
                # Recursively resolve includes in the included content
                include_path = self._resolve_include_path(base_dir, filename)
                resolved_content = self._resolve_includes(include_path, include_content)
                result_parts.append(resolved_content)
            except FileNotFoundError as e:
                # Log warning but continue - missing includes are common in PDKs
                print(f"Warning: {e}")
                # Keep the original include directive as a comment
                result_parts.append(b"* " + content[match.start() : match.end()])

            last_pos = match.end()

        # Add remaining content after last include
        result_parts.append(content[last_pos:])

        return b"".join(result_parts)

    def _resolve_include_path(self, base_dir: Path, filename: str) -> Path:
        """
        Resolve include file path, trying both relative to base and cwd.

        :param base_dir: Directory to resolve relative paths from.
        :param filename: Include filename.
        :return: Resolved include path.
        :raises FileNotFoundError: If file not found.
        """
        # Try relative to base directory first
        include_path = base_dir / filename
        if include_path.exists():
            return include_path.resolve()

        # Try relative to current working directory
        include_path = Path.cwd() / filename
        if include_path.exists():
            return include_path.resolve()

        raise FileNotFoundError(f"Include file not found: {filename} " f"(searched in {base_dir} and {Path.cwd()})")

    def _load_include_file(self, base_dir: Path, filename: str) -> bytes:
        """
        Load include file with caching.

        :param base_dir: Directory to resolve relative paths from.
        :param filename: Include filename.
        :return: File content.
        :raises FileNotFoundError: If file not found.
        """
        include_path = self._resolve_include_path(base_dir, filename)

        # Use cache to avoid re-reading the same file
        cache_key = str(include_path)
        if cache_key not in self._file_cache:
            self._file_cache[cache_key] = include_path.read_bytes()

        return self._file_cache[cache_key]

    def _resolve_includes(self, base_path: Path, content: bytes) -> bytes:
        """
        Recursively resolve .include directives in library content.

        :param base_path: Base path for resolving relative includes.
        :param content: Content to process for includes.
        :return: Content with all includes expanded.
        """
        base_dir = base_path.parent
        result_parts = []
        last_pos = 0

        for match in self.INCLUDE_PATTERN.finditer(content):
            # Add content before the include directive
            result_parts.append(content[last_pos : match.start()])

            # Process the include
            filename = match.group("filename").decode("utf-8", errors="ignore").strip("\"'")
            include_content = self._load_include_file(base_dir, filename)

            # Recursively resolve includes in the included content
            resolved_content = self._resolve_includes(base_dir / filename, include_content)
            result_parts.append(resolved_content)

            last_pos = match.end()

        # Add remaining content after last include
        result_parts.append(content[last_pos:])

        return b"".join(result_parts)

    def _load_include_file(self, base_dir: Path, filename: str) -> bytes:
        """
        Load include file with caching.

        :param base_dir: Directory to resolve relative paths from.
        :param filename: Include filename.
        :return: File content.
        :raises FileNotFoundError: If file not found.
        """
        # Try relative to base directory first
        include_path = base_dir / filename
        if not include_path.exists():
            # Try relative to current working directory
            include_path = Path.cwd() / filename
            if not include_path.exists():
                raise FileNotFoundError(
                    f"Include file not found: {filename} " f"(searched in {base_dir} and {Path.cwd()})"
                )

        # Use cache to avoid re-reading the same file
        cache_key = str(include_path.resolve())
        if cache_key not in self._file_cache:
            self._file_cache[cache_key] = include_path.read_bytes()

        return self._file_cache[cache_key]
