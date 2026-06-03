"""
Developer CLI for inspecting the netlist parse pipeline.

Not a stable public API. Intended for debugging and understanding
the data flow through Scanner → Compiler → Linker.
"""

import logging
import sys
from pathlib import Path

import click

from netlistio.graph_analysis.circuit_graph import CircuitGraph
from netlistio.ingestor.reader import SpiceReader
from netlistio.ingestor.scanner import Scanner
from netlistio.ingestor.spice import SpiceScanStrategy
from netlistio.models.parsing import RegionType
from netlistio.reporting import (
    DEFAULT_INDENT_CHAR,
    DEFAULT_INDENT_COUNT,
    DEFAULT_MODEL_SUMMARY_THRESHOLD,
    DEFAULT_PARAM_LIMIT,
    NetlistPrinter,
)

__all__ = ["cli"]

_workers_opt = click.option("--workers", "-w", default=1, show_default=True, help="Parallel worker count.")


@click.group()
@click.option("-v", "--verbose", count=True, help="Increase log verbosity. -v → INFO, -vv → DEBUG.")
@click.option("-q", "--quiet", count=True, help="Decrease log verbosity. -q → ERROR, -qq → CRITICAL.")
def cli(verbose: int, quiet: int):
    """NetlistIO debug CLI."""
    level = max(logging.DEBUG, min(logging.CRITICAL, logging.WARNING - 10 * verbose + 10 * quiet))
    # basicConfig is a no-op if handlers are already installed (e.g. in tests).
    # Force-reconfigure so the chosen level always takes effect.
    logging.root.handlers.clear()
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@cli.command("regions")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
def regions(file: Path):
    """Show scanner output — the parse regions discovered in FILE."""
    scanner = Scanner(file, SpiceScanStrategy())
    discovered = list(scanner.scan())
    if not discovered:
        click.echo("No regions found (empty file).")
        return
    click.echo(f"{'#':<4} {'Type':<8} {'Start':>10} {'End':>10}  Name")
    click.echo("-" * 55)
    for idx, region in enumerate(sorted(discovered, key=lambda r: r.start_byte)):
        label = "MACRO" if region.region_type == RegionType.MACRO else "GLOBAL"
        name = region.context_name or ""
        click.echo(f"{idx:<4} {label:<8} {region.start_byte:>10} {region.end_byte:>10}  {name}")


@cli.command("parse")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@_workers_opt
def parse(file: Path, workers: int):
    """Parse and link FILE, then print a structured summary."""
    netlist = SpiceReader().read(file, num_workers=workers)
    click.echo(f"File   : {file}")
    click.echo(f"Macros : {len(netlist.macros)}")
    click.echo(f"Top    : {len(netlist.top_instances)} instance(s)")
    if not netlist.macros:
        click.echo("(no subcircuit definitions found)")
        return
    click.echo("")
    for name, macro in netlist.macros.items():
        instances = list(macro.instances)
        primitives = sum(1 for i in instances if i.is_primitive)
        subckts = len(instances) - primitives
        port_str = ", ".join(p.name for p in macro.ports)
        click.echo(f"  .subckt {name}  ({port_str})")
        click.echo(f"    instances: {len(instances)}  primitives: {primitives}  subckts: {subckts}")


@cli.command("dump")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--indent-char", "-i", default=DEFAULT_INDENT_CHAR, show_default=True, help="Indent character.")
@click.option("--indent-count", "-c", default=DEFAULT_INDENT_COUNT, show_default=True, help="Indent count.")
@click.option("--param-limit", "-p", default=DEFAULT_PARAM_LIMIT, show_default=True, help="Parameter limit.")
@click.option(
    "--model-summary-threshold",
    "-m",
    default=DEFAULT_MODEL_SUMMARY_THRESHOLD,
    show_default=True,
    help="Model summary threshold.",
)
@_workers_opt
def dump(file: Path, workers: int, indent_char: str, indent_count: int, param_limit: int, model_summary_threshold: int):
    """Write the full linked netlist tree to stdout."""
    netlist = SpiceReader().read(file, num_workers=workers)
    NetlistPrinter(
        sys.stdout,
        indent_char=indent_char,
        indent_count=indent_count,
        param_limit=param_limit,
        model_summary_threshold=model_summary_threshold,
    ).print(netlist)


@cli.command("graph")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--subckt", "-s", default=None, help="Scope to a specific subcircuit by name.")
@click.option("--output", "-o", default=None, help="Output file path (extension selects format: svg, png, dot).")
@click.option("--engine", "-e", default="fdp", show_default=True, help="Graphviz layout engine.")
@click.option("--no-show", is_flag=True, default=False, help="Suppress interactive display.")
@click.option("--stats", is_flag=True, default=False, help="Print connectivity statistics and exit.")
@click.option(
    "--mode",
    type=click.Choice(["bipartite", "device"]),
    default="bipartite",
    show_default=True,
    help="'bipartite' (net+instance nodes, for PyG) or 'device' (instance-only, for EE analysis).",
)
@_workers_opt
def graph(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    file: Path,
    workers: int,
    subckt: str | None,
    output: str | None,
    engine: str,
    no_show: bool,
    stats: bool,
    mode: str,
):
    """Build and visualize the net/instance graph for FILE.

    Use --mode=bipartite (default) for PyG-compatible output with explicit net
    nodes, or --mode=device for an instance-only projection where edges represent
    shared nets — the natural EE connectivity view.
    """
    netlist = SpiceReader().read(file, num_workers=workers)
    if subckt:
        macro = netlist.macros.get(subckt)
        if macro is None:
            click.echo(f"Error: subcircuit '{subckt}' not found.", err=True)
            sys.exit(1)
        cg = CircuitGraph.from_macro(macro)
    else:
        cg = CircuitGraph.from_netlist(netlist)
        if not cg.nets and netlist.macros:
            names = ", ".join(netlist.macros)
            click.echo(
                f"No top-level instances found. Use --subckt to scope to one of: {names}",
                err=True,
            )
            sys.exit(1)
    if stats:
        if mode == "device":
            cg.analyze_device_connectivity()
        else:
            cg.analyze_connectivity()
        return
    if mode == "device":
        cg.visualize_device_graph(output_file=output, engine=engine, show=not no_show)
        return
    cg.visualize(output_file=output, engine=engine, show=not no_show)


@cli.command("to-pyg")
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.argument("output", type=click.Path(path_type=Path))
@click.option("--subckt", "-s", default=None, help="Scope to a specific subcircuit by name.")
@_workers_opt
def to_pyg(file: Path, output: Path, workers: int, subckt: str | None):
    """Export the bipartite graph of FILE to a PyTorch Geometric .pt file."""
    netlist = SpiceReader().read(file, num_workers=workers)
    if subckt:
        macro = netlist.macros.get(subckt)
        if macro is None:
            click.echo(f"Error: subcircuit '{subckt}' not found.", err=True)
            sys.exit(1)
        cg = CircuitGraph.from_macro(macro)
    else:
        cg = CircuitGraph.from_netlist(netlist)
    try:
        import torch  # pylint: disable=import-outside-toplevel

        data = cg.to_pyg()
        torch.save(data, output)
        click.echo(f"HeteroData saved to {output}")
    except ImportError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
