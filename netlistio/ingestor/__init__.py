"""
Netlist ingestor components for parsing, compiling, and linking.

Re-exports the extension surface so consumers implementing new format support
(e.g., Verilog) can subclass the abstract base classes without importing from
internal submodules. The SPICE concrete implementations are exposed as reference
implementations of each interface.
"""

from netlistio.ingestor.compiler import Compiler
from netlistio.ingestor.library import LibraryProcessor
from netlistio.ingestor.parser import (
    ChunkParser,
    ChunkParserFactory,
    LineParser,
    Parser,
)
from netlistio.ingestor.reader import NetlistReader, SpiceReader
from netlistio.ingestor.registry import ModelRegistry, ModelResolver
from netlistio.ingestor.scanner import ScanContext, Scanner, ScanStrategy
from netlistio.ingestor.spice import (
    SPICE_COMMENT_CHARS,
    SpiceChunkParserFactory,
    SpiceLibraryProcessor,
    SpiceLineParser,
    SpiceScanStrategy,
)

__all__ = [
    # orchestration
    "Compiler",
    "NetlistReader",
    "SpiceReader",
    # extension base classes
    "ChunkParser",
    "ChunkParserFactory",
    "LibraryProcessor",
    "LineParser",
    "ModelRegistry",
    "ModelResolver",
    "Parser",
    "ScanContext",
    "ScanStrategy",
    "Scanner",
    # SPICE reference implementations
    "SPICE_COMMENT_CHARS",
    "SpiceChunkParserFactory",
    "SpiceLibraryProcessor",
    "SpiceLineParser",
    "SpiceScanStrategy",
]
