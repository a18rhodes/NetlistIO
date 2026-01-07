from pathlib import Path
from typing import Callable, Iterable

from netlistio.ingestor.scanner import Scanner
from netlistio.models.parsing import IncludeDirective, ParseResult

ScannerFactory = Callable[[Path], Iterable[ParseResult]]
ParserFactory = Callable[[Path, Scanner], ParseResult]


class Flattener:
    """
    Abstract base class for format-specific flatteners.
    Subclasses implement format-specific include compilation logic.
    """

    def __init__(
        self,
        parse_result: ParseResult,
        scanner_factory: ScannerFactory,
        parser_factory: ParserFactory,
        strict: bool = True,
    ):
        """
        Initializes compiler with unlinked parse result.

        :param parse_result: Unlinked parse result.
        :param strict: Whether to enforce strict include resolution
                       boolean or with the strict flag in IncludeDirectives.
        """
        self.parse_result = parse_result
        self.strict = strict
        self.scanner_factory = scanner_factory
        self.parser_factory = parser_factory

    def flatten(self) -> None:
        """
        Flattens includes and returns updated parse result.

        :return: Updated ParseResult with includes flattened.
        """
        for include in self.parse_result.includes:
            if resolved := self._resolve_include(include):
                flattened = self._parse_included_file(resolved)
                self.parse_result.cells.extend(flattened.cells)
                self.parse_result.errors.extend(flattened.errors)
        return self.parse_result

    def _resolve_include(self, include: IncludeDirective) -> Path:
        """
        Flattens a single include directive.

        :param include: IncludeDirective to flatten.
        """
        include_path = Path(include.filepath)
        if include_path.is_absolute() and include_path.exists():
            return include_path
        for sibling_candidate in (include.source_file, self.parse_result.filepath):
            candidate = Path(sibling_candidate).parent / include_path
            if candidate.exists():
                return candidate
        if self.strict or include.strict:
            raise FileNotFoundError(f"Included file not found: {include_path}")
        return None

    def _parse_included_file(self, filepath: Path) -> ParseResult:
        """
        Parses an included file and returns its ParseResult.

        :param filepath: Path to the included file.
        :return: ParseResult of the included file.
        """
        scanner = self.scanner_factory(filepath)
        data = self.parser_factory(filepath, scanner).parse()
        Flattener(data, self.scanner_factory, self.parser_factory, strict=self.strict).flatten()
        return data
