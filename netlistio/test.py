# %%
import sys

from netlistio.ingestor.parser import Parser
from netlistio.ingestor.scanner import Scanner
from netlistio.ingestor.spice import SpiceChunkParserFactory, SpiceScanStrategy
from netlistio.ingestor.flattener import Flattener
from netlistio.models.spice import prefix_registry, SpiceNetlist
from netlistio.models.generic import Primitive
from netlistio.ingestor.registry import ModelRegistry
from netlistio.ingestor.linker import link


def _scanner_factory(filepath):
    return Scanner(
        filepath,
        SpiceScanStrategy(),
    )


def _parser_factory(filepath, scanner):
    return Parser(
        filepath,
        scanner,
        SpiceChunkParserFactory(),
    )


# %%
netlist_file = "/workspaces/NetlistIO/tests/data/foundry/sram/Prelayout/Spice_models/sense_amplifier.spice"
scanner = _scanner_factory(netlist_file)
print(scanner.scan())


# %%
parse_result = _parser_factory(netlist_file, scanner).parse()
print(parse_result)

# %%
Flattener(parse_result=parse_result, scanner_factory=_scanner_factory, parser_factory=_parser_factory).flatten()

# %%
# Add static primitives from SpicePrimitiveTypes
model_registry = ModelRegistry(
    static_primitives={
        primitive.name.lower(): primitive
        for primitive in prefix_registry().values()
        if isinstance(primitive, Primitive)
    }
)
link_result = link(parse_result, model_registry, SpiceNetlist)
netlist = link_result.netlist

# %%
for cell in netlist.cells:
    cell.write(sys.stdout)
