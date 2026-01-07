"""
Handles include directives and library file processing.

Provides functionality for resolving .include and .lib directives,
extracting library sections, and building complete file dependency trees.
"""

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from netlistio.ingestor.common import open_mmap
from netlistio.ingestor.scanner import ScanStrategy
from netlistio.models import IncludeDirective, LibraryDirective

__all__ = ["IncludeDirective", "LibraryDirective", "IncludeResolver"]


@dataclass
class IncludeResolver:
    """
    Resolves include directives and builds file dependency tree.

    Handles both .include and .lib directives, resolving file paths
    relative to including file or working directory.
    """

    scan_strategy: ScanStrategy
    _processed_files: set[str] = field(default_factory=set)
    _dependency_graph: nx.DiGraph = field(default_factory=nx.DiGraph)
    _includes: list[IncludeDirective] = field(default_factory=list)
    _libraries: list[LibraryDirective] = field(default_factory=list)

    def resolve_includes(self, root_file: Path) -> tuple[list[Path], list[LibraryDirective]]:
        """
        Recursively resolves all include dependencies.

        :param root_file: Starting netlist file.
        :return: Tuple of (all_files_to_process, library_directives).
        :raises FileNotFoundError: If include file cannot be found.
        :raises ValueError: If circular dependencies detected.
        """
        self._dependency_graph.add_node(str(root_file))
        self._scan_file_for_includes(root_file, root_file.parent)

        # Check for circular dependencies
        try:
            sorted_files = list(nx.topological_sort(self._dependency_graph))
        except nx.NetworkXError:
            cycle = nx.find_cycle(self._dependency_graph)
            cycle_path = " → ".join([edge[0] for edge in cycle] + [cycle[0][0]])
            raise ValueError(f"Circular include dependency: {cycle_path}")

        # Return files in dependency order
        all_files = [Path(f) for f in sorted_files if f != str(root_file)]
        all_files.insert(0, root_file)  # Root file first

        return all_files, self._libraries

    def _scan_file_for_includes(self, file_path: Path, base_dir: Path) -> None:
        """Scan file for include directives and process recursively."""
        file_str = str(file_path)
        if file_str in self._processed_files:
            return

        self._processed_files.add(file_str)

        with open_mmap(file_path) as mm:
            line_num = 1
            mm.seek(0)
            while line := mm.readline():
                if include_match := self.scan_strategy.matches_include(line):
                    self._process_include_directive(include_match, file_path, base_dir, line_num)
                line_num += 1

    def _process_include_directive(
        self, include_match: tuple[str, ...], source_file: Path, base_dir: Path, line_num: int
    ) -> None:
        """Process a single include directive."""
        if len(include_match) == 1:
            # .include directive
            include_path = self._resolve_file_path(include_match[0], base_dir)
            directive = IncludeDirective(str(include_path), str(source_file), line_num)
            self._includes.append(directive)

            # Add to dependency graph
            self._dependency_graph.add_edge(str(source_file), str(include_path))

            # Recursively process included file
            self._scan_file_for_includes(include_path, include_path.parent)

        elif len(include_match) == 2:
            # .lib directive
            lib_path = self._resolve_file_path(include_match[0], base_dir)
            section = include_match[1] if len(include_match) > 1 and include_match[1].strip() else None
            directive = LibraryDirective(str(lib_path), section, str(source_file), line_num)
            self._libraries.append(directive)

    def _resolve_file_path(self, filename: str, base_dir: Path) -> Path:
        """
        Resolve include file path, trying both relative to including file and cwd.

        :param filename: Filename from include directive.
        :param base_dir: Directory of the including file.
        :return: Resolved absolute path.
        :raises FileNotFoundError: If file cannot be found in either location.
        """
        # Remove quotes if present
        filename = filename.strip("\"'")

        # Try relative to including file first
        relative_path = base_dir / filename
        if relative_path.exists():
            return relative_path.resolve()

        # Try relative to current working directory
        cwd_path = Path.cwd() / filename
        if cwd_path.exists():
            return cwd_path.resolve()

        raise FileNotFoundError(f"Include file not found: {filename} " f"(searched in {base_dir} and {Path.cwd()})")
